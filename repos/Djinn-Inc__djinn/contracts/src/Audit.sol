// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {Purchase, Outcome, AccountState} from "./interfaces/IDjinn.sol";
import {IEscrow, ICollateral, ICreditLedger, IAccount, ISignalCommitment} from "./interfaces/IProtocol.sol";

/// @notice Minimal view interface for OutcomeVoting opt-in flag. Local to Audit
/// to avoid coupling all of IProtocol to OV's internal layout.
interface IOutcomeVotingEarlyExit {
    function earlyExitRequested(bytes32 batchKey) external view returns (bool);
}

/// @notice Result of an audit settlement
struct AuditResult {
    int256 qualityScore;
    uint256 trancheA;
    uint256 trancheB;
    uint256 protocolFee;
    uint256 timestamp;
}

/// @title Audit (v2 — Batch-based settlement)
/// @notice Handles settlement for batches of resolved purchases between a Genius-Idiot pair.
///         Validators identify 10+ resolved unaudited purchases, compute the Quality Score
///         off-chain via MPC, vote on the aggregate, and settlement fires on quorum.
///         The pair is never blocked from trading.
contract Audit is Initializable, OwnableUpgradeable, PausableUpgradeable, ReentrancyGuardTransient, UUPSUpgradeable {
    // ─── Constants
    // ──────────────────────────────────────────────

    /// @notice Protocol fee in basis points (0.5% = 50 bps)
    uint256 public constant PROTOCOL_FEE_BPS = 50;

    /// @notice Basis points denominator
    uint256 public constant BPS_DENOMINATOR = 10_000;

    /// @notice Odds precision: 6-decimal fixed point (1.91 = 1_910_000)
    uint256 public constant ODDS_PRECISION = 1e6;

    /// @notice Maximum absolute quality score (1 billion USDC, 6 decimals)
    int256 public constant MAX_QUALITY_SCORE = 1_000_000_000e6;

    /// @notice Maximum total notional per batch (20 signals * 1M USDC max per signal)
    uint256 public constant MAX_BATCH_NOTIONAL = 20e12;

    /// @notice Minimum purchases in a standard audit batch
    uint256 public constant MIN_BATCH_SIZE = 10;

    /// @notice Maximum purchases in an audit batch (gas bound)
    uint256 public constant MAX_BATCH_SIZE = 20;

    /// @notice Default auto-early-exit delay used at V2 init (45 days).
    /// @dev Per project memory: "free speech with SLA" — 45 days is the
    ///      enforceable deadline of the SLA between genius and idiot.
    uint256 public constant DEFAULT_AUTO_EARLY_EXIT_DELAY = 45 days;

    /// @notice Hard cap on autoEarlyExitDelay to prevent owner from setting
    ///         it to "never" and indefinitely parking sub-MIN_BATCH batches.
    uint256 public constant MAX_AUTO_EARLY_EXIT_DELAY = 365 days;

    /// @notice Hard floor on autoEarlyExitDelay. 1 day prevents accidental
    ///         setter calls (e.g., wrong unit) from making timeout instant.
    uint256 public constant MIN_AUTO_EARLY_EXIT_DELAY = 1 days;

    // ─── Legacy State (v1, preserved for UUPS layout) ───────────

    IEscrow public escrow;
    ICollateral public collateral;
    ICreditLedger public creditLedger;
    IAccount public account;
    ISignalCommitment public signalCommitment;
    address public protocolTreasury;
    address public outcomeVoting;

    /// @notice Stored audit results: genius -> idiot -> batchId -> AuditResult
    /// @dev In v1 this was keyed by cycle. In v2, keyed by batchId from Account.markBatchAudited.
    mapping(address => mapping(address => mapping(uint256 => AuditResult))) public auditResults;

    address public pauser;

    // ─── Events
    // ─────────────────────────────────────────────────

    event AuditSettled(
        address indexed genius,
        address indexed idiot,
        uint256 batchId,
        int256 qualityScore,
        uint256 trancheA,
        uint256 trancheB,
        uint256 protocolFee
    );

    event EarlyExitSettled(
        address indexed genius, address indexed idiot, uint256 batchId, int256 qualityScore, uint256 creditsAwarded
    );

    event ContractAddressUpdated(string name, address addr);
    event TreasuryUpdated(address newTreasury);
    event PauserUpdated(address indexed newPauser);
    event ProtocolFeeShortfall(address indexed genius, uint256 intended, uint256 actual);
    event ForceSettlement(address indexed genius, address indexed idiot, uint256 batchId, int256 qualityScore);

    // ─── V2 events
    // ─────────────────────────────────────────────
    event AutoEarlyExitDelayUpdated(uint256 oldDelay, uint256 newDelay);

    // ─── Errors
    // ─────────────────────────────────────────────────

    error AlreadySettled(address genius, address idiot, uint256 batchId);
    error ZeroAddress();
    error ContractNotSet(string name);
    error NotPartyToAudit(address caller, address genius, address idiot);
    error NoPurchasesInBatch();
    error OutcomesNotFinalized(address genius, address idiot);
    error CallerNotOutcomeVoting(address caller);
    error QualityScoreOutOfBounds(int256 score, int256 maxAbsolute);
    error NotPauserOrOwner(address caller);
    error TotalNotionalOutOfBounds(uint256 totalNotional, uint256 maxAllowed);
    error BatchTooSmall(uint256 provided, uint256 minimum);
    error BatchTooLarge(uint256 provided, uint256 maximum);

    // ─── V2 errors
    // ─────────────────────────────────────────────
    error EarlyExitNotPermitted(bytes32 batchKey, uint256 latestPurchaseAt, uint256 requiredAfter);
    error AutoEarlyExitDelayOutOfBounds(uint256 provided, uint256 min, uint256 max);
    error AlreadyInitializedV2();

    // ─── Constructor
    // ────────────────────────────────────────────

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function initialize(address _owner) public initializer {
        __Ownable_init(_owner);
        __Pausable_init();
    }

    // ─── Admin
    // ──────────────────────────────────────────────────

    function setEscrow(address _addr) external onlyOwner {
        if (_addr == address(0)) revert ZeroAddress();
        escrow = IEscrow(_addr);
        emit ContractAddressUpdated("Escrow", _addr);
    }

    function setCollateral(address _addr) external onlyOwner {
        if (_addr == address(0)) revert ZeroAddress();
        collateral = ICollateral(_addr);
        emit ContractAddressUpdated("Collateral", _addr);
    }

    function setCreditLedger(address _addr) external onlyOwner {
        if (_addr == address(0)) revert ZeroAddress();
        creditLedger = ICreditLedger(_addr);
        emit ContractAddressUpdated("CreditLedger", _addr);
    }

    function setAccount(address _addr) external onlyOwner {
        if (_addr == address(0)) revert ZeroAddress();
        account = IAccount(_addr);
        emit ContractAddressUpdated("Account", _addr);
    }

    function setSignalCommitment(address _addr) external onlyOwner {
        if (_addr == address(0)) revert ZeroAddress();
        signalCommitment = ISignalCommitment(_addr);
        emit ContractAddressUpdated("SignalCommitment", _addr);
    }

    function setProtocolTreasury(address _treasury) external onlyOwner {
        if (_treasury == address(0)) revert ZeroAddress();
        protocolTreasury = _treasury;
        emit TreasuryUpdated(_treasury);
    }

    function setOutcomeVoting(address _addr) external onlyOwner {
        if (_addr == address(0)) revert ZeroAddress();
        outcomeVoting = _addr;
        emit ContractAddressUpdated("OutcomeVoting", _addr);
    }

    // ─── V2: Auto-early-exit timeout
    // ────────────────────────────

    /// @notice One-shot post-upgrade initializer for V2 state.
    /// @dev Idempotent via the `autoEarlyExitDelay == 0` sentinel. After init
    ///      the value is always >= MIN_AUTO_EARLY_EXIT_DELAY (1 day) so this
    ///      can never accidentally re-initialize. Owner-only (= timelock).
    function initializeV2() external onlyOwner {
        if (autoEarlyExitDelay != 0) revert AlreadyInitializedV2();
        autoEarlyExitDelay = DEFAULT_AUTO_EARLY_EXIT_DELAY;
        emit AutoEarlyExitDelayUpdated(0, DEFAULT_AUTO_EARLY_EXIT_DELAY);
    }

    /// @notice Update the auto-early-exit delay. Bounded [1 day, 365 days].
    ///         Lower values let stuck sub-MIN_BATCH batches resolve faster but
    ///         increase the chance of timeout-triggered settlement on pairs
    ///         that are still actively trading.
    function setAutoEarlyExitDelay(uint256 newDelay) external onlyOwner {
        if (newDelay < MIN_AUTO_EARLY_EXIT_DELAY || newDelay > MAX_AUTO_EARLY_EXIT_DELAY) {
            revert AutoEarlyExitDelayOutOfBounds(newDelay, MIN_AUTO_EARLY_EXIT_DELAY, MAX_AUTO_EARLY_EXIT_DELAY);
        }
        uint256 old = autoEarlyExitDelay;
        autoEarlyExitDelay = newDelay;
        emit AutoEarlyExitDelayUpdated(old, newDelay);
    }

    // ─── Core: Permissionless settlement
    // ────────────────────────

    /// @notice Settle a batch of resolved purchases. Permissionless: anyone can call.
    ///         All outcomes must be recorded on-chain (non-voted path).
    /// @param genius The Genius address
    /// @param idiot The Idiot address
    /// @param purchaseIds The purchases to settle (must be 10-20, all resolved, all unaudited)
    function settle(address genius, address idiot, uint256[] calldata purchaseIds) external whenNotPaused nonReentrant {
        _validateDependencies();
        _validateBatchSize(purchaseIds.length, MIN_BATCH_SIZE);
        _verifyAllOutcomesFinalized(genius, idiot, purchaseIds);

        int256 score = _computeScore(genius, idiot, purchaseIds);
        (uint256 totalNotional, uint256 totalUsdcFeesPaid) = _aggregatePurchases(genius, idiot, purchaseIds);

        uint256 batchId = account.markBatchAudited(genius, idiot, purchaseIds);
        _settleCommon(genius, idiot, batchId, score, false, totalNotional, totalUsdcFeesPaid, purchaseIds);
    }

    /// @notice Either party can trigger early exit for fewer than 10 resolved purchases.
    /// @param genius The Genius address
    /// @param idiot The Idiot address
    /// @param purchaseIds The purchases to settle (1-9, all resolved, all unaudited)
    function earlyExit(address genius, address idiot, uint256[] calldata purchaseIds)
        external
        whenNotPaused
        nonReentrant
    {
        _validateDependencies();
        if (msg.sender != genius && msg.sender != idiot) {
            revert NotPartyToAudit(msg.sender, genius, idiot);
        }
        if (purchaseIds.length == 0) revert NoPurchasesInBatch();
        if (purchaseIds.length > MAX_BATCH_SIZE) revert BatchTooLarge(purchaseIds.length, MAX_BATCH_SIZE);
        _verifyAllOutcomesFinalized(genius, idiot, purchaseIds);

        int256 score = _computeScore(genius, idiot, purchaseIds);
        (uint256 totalNotional, uint256 totalUsdcFeesPaid) = _aggregatePurchases(genius, idiot, purchaseIds);

        uint256 batchId = account.markBatchAudited(genius, idiot, purchaseIds);
        _settleCommon(genius, idiot, batchId, score, true, totalNotional, totalUsdcFeesPaid, purchaseIds);
    }

    // ─── Voted settlement (called by OutcomeVoting) ─────────────

    /// @notice Settle a full batch using a validator-voted quality score.
    function settleByVote(
        address genius,
        address idiot,
        uint256[] calldata purchaseIds,
        int256 qualityScore,
        uint256 totalNotional
    ) external whenNotPaused nonReentrant {
        if (msg.sender != outcomeVoting) revert CallerNotOutcomeVoting(msg.sender);
        _validateScoreAndNotional(qualityScore, totalNotional);
        _validateDependencies();
        _validateBatchSize(purchaseIds.length, MIN_BATCH_SIZE);

        // Mark as audited in Account (validates purchases are valid)
        uint256 batchId = account.markBatchAudited(genius, idiot, purchaseIds);

        // Compute USDC fees from on-chain records for damage cap
        uint256 totalUsdcFeesPaid;
        uint256 onChainNotional;
        for (uint256 i; i < purchaseIds.length; ++i) {
            Purchase memory p = escrow.getPurchase(purchaseIds[i]);
            totalUsdcFeesPaid += p.usdcPaid;
            onChainNotional += p.notional;
        }
        if (totalNotional > onChainNotional) {
            revert TotalNotionalOutOfBounds(totalNotional, onChainNotional);
        }

        // Use on-chain notional for settlement math instead of the
        // validator-supplied value. The bounds check above catches gross
        // mismatches; using onChainNotional removes the attack vector where
        // a validator zeros totalNotional to eliminate protocol fees.
        _settleCommon(genius, idiot, batchId, qualityScore, false, onChainNotional, totalUsdcFeesPaid, purchaseIds);
    }

    /// @notice Settle an early exit batch using a validator-voted quality score.
    /// @dev V2 precondition: caller must satisfy at least one of
    ///      (a) OV.earlyExitRequested[batchKey] == true (genius or idiot opted in via OV.requestEarlyExit), or
    ///      (b) block.timestamp >= max(p.purchasedAt) + autoEarlyExitDelay (SLA timeout fired).
    ///      Otherwise reverts with EarlyExitNotPermitted. Validator quorum
    ///      (3-of-N) cannot bypass this — the precondition is on-chain so a
    ///      colluding majority can't sneak credits-only settlement onto a
    ///      fresh pair without consent.
    function earlyExitByVote(
        address genius,
        address idiot,
        uint256[] calldata purchaseIds,
        int256 qualityScore,
        uint256 totalNotional
    ) external whenNotPaused nonReentrant {
        if (msg.sender != outcomeVoting) revert CallerNotOutcomeVoting(msg.sender);
        _validateScoreAndNotional(qualityScore, totalNotional);
        _validateDependencies();
        if (purchaseIds.length == 0) revert NoPurchasesInBatch();
        if (purchaseIds.length > MAX_BATCH_SIZE) revert BatchTooLarge(purchaseIds.length, MAX_BATCH_SIZE);

        // V2 precondition check before doing any on-chain mutations.
        _validateEarlyExitPermitted(genius, idiot, purchaseIds);

        uint256 batchId = account.markBatchAudited(genius, idiot, purchaseIds);

        uint256 totalUsdcFeesPaid;
        uint256 onChainNotional;
        for (uint256 i; i < purchaseIds.length; ++i) {
            Purchase memory p = escrow.getPurchase(purchaseIds[i]);
            totalUsdcFeesPaid += p.usdcPaid;
            onChainNotional += p.notional;
        }
        if (totalNotional > onChainNotional) {
            revert TotalNotionalOutOfBounds(totalNotional, onChainNotional);
        }

        _settleCommon(genius, idiot, batchId, qualityScore, true, onChainNotional, totalUsdcFeesPaid, purchaseIds);
    }

    /// @notice Check that early-exit-by-vote is permitted: either explicit
    ///         opt-in via OV.requestEarlyExit, or auto-timeout elapsed.
    /// @dev Reverts with EarlyExitNotPermitted otherwise. View-only.
    function _validateEarlyExitPermitted(address genius, address idiot, uint256[] calldata purchaseIds) internal view {
        bytes32 batchKey = keccak256(abi.encode(genius, idiot, keccak256(abi.encode(purchaseIds))));

        // Path 1: explicit opt-in via either party. Cheapest check first.
        if (IOutcomeVotingEarlyExit(outcomeVoting).earlyExitRequested(batchKey)) {
            return;
        }

        // Path 2: SLA timeout. Defensive default: if autoEarlyExitDelay is 0
        // (V2 not yet initialized), require explicit opt-in only.
        uint256 delay = autoEarlyExitDelay;
        if (delay == 0) {
            revert EarlyExitNotPermitted(batchKey, 0, 0);
        }

        uint256 latestPurchaseAt;
        for (uint256 i; i < purchaseIds.length; ++i) {
            uint256 t = escrow.getPurchase(purchaseIds[i]).purchasedAt;
            if (t > latestPurchaseAt) latestPurchaseAt = t;
        }

        uint256 requiredAfter = latestPurchaseAt + delay;
        if (block.timestamp < requiredAfter) {
            revert EarlyExitNotPermitted(batchKey, latestPurchaseAt, requiredAfter);
        }
    }

    // ─── Owner-only emergency settlement
    // ────────────────────────

    /// @notice Emergency settlement for stuck batches. Owner specifies quality score.
    function forceSettle(address genius, address idiot, uint256[] calldata purchaseIds, int256 qualityScore)
        external
        onlyOwner
        whenNotPaused
        nonReentrant
    {
        _validateScoreAndNotional(qualityScore, 0);
        _validateDependencies();
        if (purchaseIds.length == 0) revert NoPurchasesInBatch();
        if (purchaseIds.length > MAX_BATCH_SIZE) revert BatchTooLarge(purchaseIds.length, MAX_BATCH_SIZE);

        uint256 batchId = account.markBatchAudited(genius, idiot, purchaseIds);

        (uint256 totalNotional, uint256 totalUsdcFeesPaid) = _aggregatePurchases(genius, idiot, purchaseIds);

        // Re-enforce MAX_BATCH_NOTIONAL against the aggregated on-chain notional.
        // _validateScoreAndNotional was called above with notional=0 (we hadn't
        // yet aggregated). Defense-in-depth: even though MAX_BATCH_SIZE × per-
        // purchase MAX_NOTIONAL equals MAX_BATCH_NOTIONAL today, future changes
        // to either constant must not silently widen forceSettle.
        if (totalNotional > MAX_BATCH_NOTIONAL) {
            revert TotalNotionalOutOfBounds(totalNotional, MAX_BATCH_NOTIONAL);
        }

        bool isEarlyExit = purchaseIds.length < MIN_BATCH_SIZE;
        emit ForceSettlement(genius, idiot, batchId, qualityScore);
        _settleCommon(genius, idiot, batchId, qualityScore, isEarlyExit, totalNotional, totalUsdcFeesPaid, purchaseIds);
    }

    // ─── Score computation
    // ──────────────────────────────────────

    /// @notice Compute the Quality Score for a batch of purchases (on-chain outcomes).
    function computeScore(address genius, address idiot, uint256[] calldata purchaseIds)
        external
        view
        returns (int256)
    {
        _validateDependenciesView();
        return _computeScore(genius, idiot, purchaseIds);
    }

    // ─── Internal
    // ───────────────────────────────────────────────

    function _computeScore(address genius, address idiot, uint256[] calldata purchaseIds)
        internal
        view
        returns (int256 score)
    {
        if (purchaseIds.length == 0) revert NoPurchasesInBatch();

        for (uint256 i; i < purchaseIds.length; ++i) {
            Purchase memory p = escrow.getPurchase(purchaseIds[i]);
            Outcome outcome = account.getOutcome(genius, idiot, purchaseIds[i]);

            if (outcome == Outcome.Favorable) {
                int256 gain = int256(p.notional) * (int256(p.odds) - int256(ODDS_PRECISION)) / int256(ODDS_PRECISION);
                score += gain;
            } else if (outcome == Outcome.Unfavorable) {
                uint256 slaBps = signalCommitment.getSignalSlaMultiplierBps(p.signalId);
                int256 loss = int256(p.notional) * int256(slaBps) / int256(BPS_DENOMINATOR);
                score -= loss;
            }

            if (score > MAX_QUALITY_SCORE || score < -MAX_QUALITY_SCORE) {
                revert QualityScoreOutOfBounds(score, MAX_QUALITY_SCORE);
            }
        }
    }

    function _aggregatePurchases(address genius, address idiot, uint256[] calldata purchaseIds)
        internal
        view
        returns (uint256 totalNotional, uint256 totalUsdcFeesPaid)
    {
        for (uint256 i; i < purchaseIds.length; ++i) {
            Purchase memory p = escrow.getPurchase(purchaseIds[i]);
            Outcome outcome = account.getOutcome(genius, idiot, purchaseIds[i]);
            if (outcome != Outcome.Void) {
                totalNotional += p.notional;
            }
            totalUsdcFeesPaid += p.usdcPaid;
        }
    }

    function _verifyAllOutcomesFinalized(address genius, address idiot, uint256[] calldata purchaseIds) internal view {
        for (uint256 i; i < purchaseIds.length; ++i) {
            Outcome outcome = account.getOutcome(genius, idiot, purchaseIds[i]);
            if (outcome == Outcome.Pending) {
                revert OutcomesNotFinalized(genius, idiot);
            }
        }
    }

    function _distributeDamages(address genius, address idiot, uint256 totalDamages, uint256 totalUsdcFeesPaid)
        internal
        returns (uint256 trancheA, uint256 trancheB)
    {
        trancheA = totalDamages < totalUsdcFeesPaid ? totalDamages : totalUsdcFeesPaid;
        if (totalDamages > trancheA) {
            trancheB = totalDamages - trancheA;
        }

        if (trancheA > 0) {
            try collateral.slash(genius, trancheA, idiot) returns (uint256 actualSlash) {
                if (actualSlash < trancheA) {
                    uint256 shortfall = trancheA - actualSlash;
                    trancheB += shortfall;
                    trancheA = actualSlash;
                }
            } catch {
                trancheB += trancheA;
                trancheA = 0;
            }
        }

        if (trancheB > 0) {
            creditLedger.mint(idiot, trancheB);
        }
    }

    function _releaseSignalLocks(address genius, uint256[] memory purchaseIds) internal {
        for (uint256 i; i < purchaseIds.length; ++i) {
            Purchase memory p = escrow.getPurchase(purchaseIds[i]);
            uint256 slaBps = signalCommitment.getSignalSlaMultiplierBps(p.signalId);
            uint256 slaLock = (p.notional * slaBps) / BPS_DENOMINATOR;
            uint256 protocolFeeLock = (p.notional * PROTOCOL_FEE_BPS) / BPS_DENOMINATOR;
            uint256 expectedLock = slaLock + protocolFeeLock;
            uint256 actualLock = collateral.getSignalLock(genius, p.signalId);
            uint256 releaseAmount = expectedLock < actualLock ? expectedLock : actualLock;
            if (releaseAmount > 0) {
                collateral.release(p.signalId, genius, releaseAmount);
            }
        }
    }

    function _settleCommon(
        address genius,
        address idiot,
        uint256 batchId,
        int256 score,
        bool isEarlyExit,
        uint256 totalNotional,
        uint256 totalUsdcFeesPaid,
        uint256[] memory purchaseIds
    ) internal {
        collateral.freezeWithdrawals(genius);

        uint256 protocolFee = (totalNotional * PROTOCOL_FEE_BPS) / BPS_DENOMINATOR;

        _releaseSignalLocks(genius, purchaseIds);

        uint256 trancheA;
        uint256 trancheB;

        // V2 invariant: damages currency is determined by what the idiot paid,
        // not by which settlement entrypoint was used. Both paths route through
        // _distributeDamages, which caps trancheA at totalUsdcFeesPaid (sum of
        // p.usdcPaid across the batch). Credit-funded purchases contribute 0
        // to the cap, so a credit-only purchaser never extracts USDC. A USDC
        // purchaser gets back at most what they paid, never net-profit.
        // See feedback_settlement_consent_or_timeout.md and
        // feedback_credits_in_credits_out.md.
        if (score < 0) {
            (trancheA, trancheB) = _distributeDamages(genius, idiot, uint256(-score), totalUsdcFeesPaid);
        }

        // Compute net claimable fees and record in Escrow (replaces feePool)
        uint256 netClaimable = totalUsdcFeesPaid > trancheA ? totalUsdcFeesPaid - trancheA : 0;
        if (netClaimable > 0) {
            escrow.recordBatchClaimable(genius, idiot, batchId, netClaimable);
        }

        if (protocolFee > 0) {
            uint256 intendedFee = protocolFee;
            protocolFee = collateral.slash(genius, protocolFee, protocolTreasury);
            if (protocolFee < intendedFee) {
                emit ProtocolFeeShortfall(genius, intendedFee, protocolFee);
            }
        }

        auditResults[genius][idiot][batchId] = AuditResult({
            qualityScore: score,
            trancheA: trancheA,
            trancheB: trancheB,
            protocolFee: protocolFee,
            timestamp: block.timestamp
        });

        collateral.unfreezeWithdrawals(genius);

        // V2: AuditSettled is now the canonical settlement event for both
        // paths so indexers see uniform trancheA/trancheB/protocolFee data
        // regardless of entrypoint. EarlyExitSettled is also emitted on the
        // early-exit path for backwards-compatible listeners.
        emit AuditSettled(genius, idiot, batchId, score, trancheA, trancheB, protocolFee);
        if (isEarlyExit) {
            emit EarlyExitSettled(genius, idiot, batchId, score, trancheB);
        }
    }

    // ─── View
    // ───────────────────────────────────────────────────

    function getAuditResult(address genius, address idiot, uint256 batchId) external view returns (AuditResult memory) {
        return auditResults[genius][idiot][batchId];
    }

    // ─── Validation helpers
    // ─────────────────────────────────────

    function _validateBatchSize(uint256 size, uint256 minimum) internal pure {
        if (size < minimum) revert BatchTooSmall(size, minimum);
        if (size > MAX_BATCH_SIZE) revert BatchTooLarge(size, MAX_BATCH_SIZE);
    }

    function _validateScoreAndNotional(int256 score, uint256 notional) internal pure {
        if (score > MAX_QUALITY_SCORE || score < -MAX_QUALITY_SCORE) {
            revert QualityScoreOutOfBounds(score, MAX_QUALITY_SCORE);
        }
        if (notional > MAX_BATCH_NOTIONAL) {
            revert TotalNotionalOutOfBounds(notional, MAX_BATCH_NOTIONAL);
        }
    }

    function _validateDependencies() internal view {
        if (address(escrow) == address(0)) revert ContractNotSet("Escrow");
        if (address(collateral) == address(0)) revert ContractNotSet("Collateral");
        if (address(creditLedger) == address(0)) revert ContractNotSet("CreditLedger");
        if (address(account) == address(0)) revert ContractNotSet("Account");
        if (address(signalCommitment) == address(0)) revert ContractNotSet("SignalCommitment");
        if (protocolTreasury == address(0)) revert ContractNotSet("ProtocolTreasury");
    }

    function _validateDependenciesView() internal view {
        if (address(escrow) == address(0)) revert ContractNotSet("Escrow");
        if (address(account) == address(0)) revert ContractNotSet("Account");
        if (address(signalCommitment) == address(0)) revert ContractNotSet("SignalCommitment");
    }

    // ─── Emergency pause
    // ────────────────────────────────────────

    function setPauser(address _pauser) external onlyOwner {
        pauser = _pauser;
        emit PauserUpdated(_pauser);
    }

    function pause() external {
        if (msg.sender != pauser && msg.sender != owner()) revert NotPauserOrOwner(msg.sender);
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function _authorizeUpgrade(address) internal override onlyOwner whenPaused {}

    function renounceOwnership() public pure override {
        revert("disabled");
    }

    // ─── V2 State (auto-early-exit timeout) ─────────────────────
    // Inserted into the head of the original __gap, so the on-chain storage
    // layout is preserved across the UUPS upgrade.

    /// @notice Delay (in seconds) since the last purchase in a (genius, idiot)
    ///         pair after which validator quorum can auto-trigger early-exit
    ///         settlement, even without an explicit OV.requestEarlyExit.
    /// @dev Settable via setAutoEarlyExitDelay (onlyOwner = timelock). A value
    ///      of 0 means "uninitialized" (pre-V2-init). After initializeV2 it is
    ///      always > 0 and <= MAX_AUTO_EARLY_EXIT_DELAY.
    uint256 public autoEarlyExitDelay;

    /// @dev Reserved storage gap for future upgrades.
    /// Reduced from 41 to 40 to make room for autoEarlyExitDelay.
    uint256[40] private __gap;
}
