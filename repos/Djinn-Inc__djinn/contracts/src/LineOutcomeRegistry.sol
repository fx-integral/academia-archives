// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {EIP712Upgradeable} from "@openzeppelin/contracts-upgradeable/utils/cryptography/EIP712Upgradeable.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

interface IValidatorRegistry {
    function isValidator(address) external view returns (bool);
}

/// @title LineOutcomeRegistry — canonical per-line sports outcome registry
/// @notice Validators attest the outcome of a single (sport, event, market, side, line)
///         tuple keyed by lineHash. Once 4-of-5 attestations agree, the outcome is
///         finalized and immutable. Designed to feed deterministic inputs into the
///         existing OutcomeVoting + Audit settlement path.
/// @dev    Trust model: 4-of-5 honest-supermajority of OutcomeVoting signer set.
///         An attestation, once accepted, remains counted even if the signer is
///         later removed from the validator set. This is intentional: prevents
///         validator-set churn from undoing already-collected agreement. See
///         docs/v1747-line-schema.md for the canonical schema and golden vectors.
contract LineOutcomeRegistry is
    Initializable,
    OwnableUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable,
    EIP712Upgradeable
{
    enum Outcome {
        Pending,
        Favorable,
        Unfavorable,
        Void
    }

    string public constant NAME = "DjinnLineOutcomeRegistry";
    string public constant VERSION = "1";

    /// @notice EIP-712 typehash for a line attestation.
    bytes32 public constant ATTEST_TYPEHASH =
        keccak256("LineAttestation(bytes32 lineHash,uint8 outcome,bytes32 rulesetHash)");

    /// @notice Immutable schema/ruleset identifier. Schema changes deploy a new
    ///         contract; this contract serves DJINN_OUTCOMES_V1 forever.
    bytes32 public constant OUTCOME_RULESET_HASH = keccak256("DJINN_OUTCOMES_V1");

    /// @notice Number of distinct validator attestations required to finalize a line.
    uint8 public constant THRESHOLD = 4;

    /// @notice Source of validator set membership. Wired to OutcomeVoting at init time.
    IValidatorRegistry public validatorRegistry;

    /// @notice Canonical outcome per line. Pending until threshold reached.
    mapping(bytes32 => Outcome) public lineOutcome;
    /// @notice Block timestamp when the line was finalized (0 if Pending).
    mapping(bytes32 => uint64) public lineFinalizedAt;

    /// @notice Per-line per-validator attestation. Outcome.Pending sentinel = unattested.
    ///         Once set, never reset — attestations are sticky through validator-set
    ///         churn. Trust model = 4-of-5 of signers who attested at the time of
    ///         attestation, not the current signer set.
    mapping(bytes32 => mapping(address => Outcome)) public attestation;

    /// @dev Per-line, per-outcome count. Storage-efficient (uint8 fits up to 255 sigs).
    mapping(bytes32 => mapping(uint8 => uint8)) private _claimCount;

    /// @dev Reserved storage for future versions. Slot accounting: 5 storage
    ///      slots used (validatorRegistry, lineOutcome, lineFinalizedAt,
    ///      attestation, _claimCount) + 45 reserved = 50 total. When adding
    ///      new state in v2, decrement the gap by N for each new slot.
    uint256[45] private __gap;

    event LineAttested(bytes32 indexed lineHash, address indexed attestor, Outcome outcome);
    event LineFinalized(bytes32 indexed lineHash, Outcome outcome, uint64 finalizedAt);
    event LineForceVoided(bytes32 indexed lineHash, string reason);

    error AlreadyFinalized();
    error NotInValidatorSet();
    error AlreadyAttested();
    error InvalidOutcome();
    error BadSignature();
    error LengthMismatch();
    error ZeroAddress();

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function initialize(address _owner, address _validatorRegistry) external initializer {
        if (_owner == address(0) || _validatorRegistry == address(0)) revert ZeroAddress();
        __Ownable_init(_owner);
        __Pausable_init();
        __EIP712_init(NAME, VERSION);
        validatorRegistry = IValidatorRegistry(_validatorRegistry);
    }

    // ─── Public attestation ───────────────────────────────────────────────────

    /// @notice Submit one or more (signer, signature) pairs for a single (lineHash, outcome).
    ///         Permissionless: any caller may submit; signers must be in the current
    ///         validator set. Already-attested signers are SKIPPED (no revert) so
    ///         racing submitters with overlapping bundles don't poison each other.
    /// @param lineHash    keccak256(abi.encodePacked("DJINN_LINE_V1", chainId, address(this), canonicalString))
    /// @param outcome     One of {Favorable, Unfavorable, Void}. Pending is invalid.
    /// @param signers     Addresses corresponding 1:1 to signatures.
    /// @param signatures  EIP-712 ECDSA signatures over (lineHash, outcome, OUTCOME_RULESET_HASH).
    function submitLineOutcome(
        bytes32 lineHash,
        Outcome outcome,
        address[] calldata signers,
        bytes[] calldata signatures
    ) external whenNotPaused {
        if (signers.length != signatures.length) revert LengthMismatch();
        if (signers.length == 0) revert LengthMismatch();
        if (outcome == Outcome.Pending) revert InvalidOutcome();
        if (lineOutcome[lineHash] != Outcome.Pending) revert AlreadyFinalized();

        bytes32 digest = _hashTypedDataV4(
            keccak256(abi.encode(ATTEST_TYPEHASH, lineHash, uint8(outcome), OUTCOME_RULESET_HASH))
        );

        uint8 outcomeIdx = uint8(outcome);
        for (uint256 i; i < signers.length;) {
            address signer = signers[i];
            // Skip-already-attested: racing submitters can submit overlapping
            // bundles without reverting each other.
            if (attestation[lineHash][signer] == Outcome.Pending) {
                if (!validatorRegistry.isValidator(signer)) revert NotInValidatorSet();
                if (ECDSA.recover(digest, signatures[i]) != signer) revert BadSignature();

                attestation[lineHash][signer] = outcome;
                uint8 c = ++_claimCount[lineHash][outcomeIdx];
                emit LineAttested(lineHash, signer, outcome);

                if (c >= THRESHOLD && lineOutcome[lineHash] == Outcome.Pending) {
                    lineOutcome[lineHash] = outcome;
                    lineFinalizedAt[lineHash] = uint64(block.timestamp);
                    emit LineFinalized(lineHash, outcome, uint64(block.timestamp));
                }
            }
            unchecked {
                ++i;
            }
        }
    }

    // ─── Operator escape hatch ────────────────────────────────────────────────

    /// @notice Operator override for stuck lines (genuine ESPN ambiguity, validator
    ///         churn that broke a near-finalized cohort, etc). Always Voids; never
    ///         dictates a Favorable/Unfavorable outcome.
    /// @dev    onlyOwner via TimelockController. Off-chain operator policy SHOULD
    ///         require multi-sig approval before scheduling this; the contract
    ///         enforces only the timelock.
    function forceVoid(bytes32 lineHash, string calldata reason) external onlyOwner {
        if (lineOutcome[lineHash] != Outcome.Pending) revert AlreadyFinalized();
        lineOutcome[lineHash] = Outcome.Void;
        lineFinalizedAt[lineHash] = uint64(block.timestamp);
        emit LineForceVoided(lineHash, reason);
        emit LineFinalized(lineHash, Outcome.Void, uint64(block.timestamp));
    }

    // ─── Reads ────────────────────────────────────────────────────────────────

    /// @notice True if the line has reached threshold and has a non-Pending outcome.
    function isFinalized(bytes32 lineHash) external view returns (bool) {
        return lineOutcome[lineHash] != Outcome.Pending;
    }

    /// @notice Batch read for MPC-side consumption. Returns Outcome[].
    function batchOutcomes(bytes32[] calldata hashes) external view returns (Outcome[] memory out) {
        out = new Outcome[](hashes.length);
        for (uint256 i; i < hashes.length;) {
            out[i] = lineOutcome[hashes[i]];
            unchecked {
                ++i;
            }
        }
    }

    /// @notice Number of attestations recorded for a given (line, outcome) pair.
    function getClaimCount(bytes32 lineHash, Outcome o) external view returns (uint8) {
        return _claimCount[lineHash][uint8(o)];
    }

    /// @notice Compute the canonical lineHash for a string. Pure; matches Python.
    /// @dev    See docs/v1747-line-schema.md §2 for the canonical encoding.
    function computeLineHash(string memory canonicalString) external view returns (bytes32) {
        return keccak256(
            abi.encodePacked("DJINN_LINE_V1", block.chainid, address(this), canonicalString)
        );
    }

    /// @notice Compute the EIP-712 attestation digest for given (lineHash, outcome).
    ///         Useful for off-chain test cross-checks.
    function computeAttestDigest(bytes32 lineHash, Outcome outcome) external view returns (bytes32) {
        return _hashTypedDataV4(
            keccak256(abi.encode(ATTEST_TYPEHASH, lineHash, uint8(outcome), OUTCOME_RULESET_HASH))
        );
    }

    /// @notice Public domain separator accessor for off-chain tooling.
    function domainSeparatorV4() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    // ─── Admin ────────────────────────────────────────────────────────────────

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function _authorizeUpgrade(address newImpl) internal override onlyOwner whenPaused {
        if (newImpl == address(0)) revert ZeroAddress();
    }

    /// @dev Disable renounceOwnership to prevent accidental orphaning.
    function renounceOwnership() public pure override {
        revert("disabled");
    }
}
