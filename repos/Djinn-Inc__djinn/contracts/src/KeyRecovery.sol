// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";

/// @title KeyRecovery
/// @notice Stores encrypted key recovery blobs associated with wallet addresses.
///         Users encrypt their signal decryption keys to their wallet public key and
///         store the blob on-chain. This enables key recovery from any device: the user
///         logs in with their wallet, pulls the blob, and decrypts locally.
/// @dev No access control beyond msg.sender: only the wallet owner can store their blob,
///      and anyone can read any blob (it is encrypted, so reading reveals nothing).
///      UUPS upgradeable: owner (TimelockController) can push new impls. Mainnet can't
///      migrate stored blobs without user action, so the proxy pattern is the ONLY path
///      to fix a post-launch bug (blob-size DoS, storage regret, etc.). MAINNET_BLOCKERS P1-18.
///      Pausable: emergency-response coverage for all 7 user-facing contracts. Writes
///      (storeRecoveryBlob) are gated by whenNotPaused; reads (getRecoveryBlob) stay open
///      so users can always recover during a pause window. MAINNET_BLOCKERS P1-27.
contract KeyRecovery is Initializable, OwnableUpgradeable, PausableUpgradeable, UUPSUpgradeable {
    // -------------------------------------------------------------------------
    // Storage
    // -------------------------------------------------------------------------

    /// @dev wallet address => encrypted recovery blob
    mapping(address => bytes) private _recoveryBlobs;

    /// @notice Address authorized to pause this contract in emergencies
    address public pauser;

    // -------------------------------------------------------------------------
    // Events
    // -------------------------------------------------------------------------

    /// @notice Emitted when a user stores or overwrites their recovery blob
    event RecoveryBlobStored(address indexed user, uint256 timestamp);

    /// @notice Emitted when the pauser address is updated
    event PauserUpdated(address indexed newPauser);

    // -------------------------------------------------------------------------
    // Errors
    // -------------------------------------------------------------------------

    /// @notice Recovery blob must not be empty
    error EmptyBlob();

    /// @notice Recovery blob exceeds maximum allowed size
    error BlobTooLarge(uint256 size, uint256 maxSize);

    /// @notice Caller is not the pauser or the owner
    error NotPauserOrOwner(address caller);

    /// @notice Maximum blob size (4 KB, plenty for encrypted AES keys)
    uint256 public constant MAX_BLOB_SIZE = 4096;

    // -------------------------------------------------------------------------
    // Constructor / Initializer
    // -------------------------------------------------------------------------

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /// @notice Initializes the KeyRecovery contract (replaces constructor for proxy pattern)
    /// @param initialOwner Address that will own this contract (timelock)
    function initialize(address initialOwner) public initializer {
        __Ownable_init(initialOwner);
        __Pausable_init();
    }

    /// @notice Re-initializer for existing pre-Pausable proxies (MAINNET_BLOCKERS P1-27).
    ///         Existing deployments were initialized on v1 (no Pausable). On v2 upgrade,
    ///         schedule `initializeV2()` via the timelock to wire the Pausable storage
    ///         slot. Idempotent: reinitializer(2) fires exactly once per impl-upgrade.
    ///         The ERC-7201 Pausable slot defaults to unpaused, so no state migration
    ///         is needed beyond emitting the Initialized(2) event for observability.
    /// @dev onlyOwner prevents a front-runner from burning the reinitializer(2) version
    ///      between a non-atomic `upgradeTo` + separate `initializeV2` pair. The intended
    ///      atomic path `upgradeToAndCall(newImpl, initializeV2Data)` still works because
    ///      msg.sender is preserved across the delegatecall, so the timelock (owner)
    ///      passes the onlyOwner check.
    function initializeV2() public onlyOwner reinitializer(2) {
        __Pausable_init();
    }

    // -------------------------------------------------------------------------
    // External Functions
    // -------------------------------------------------------------------------

    /// @notice Store or overwrite the encrypted key recovery blob for msg.sender.
    ///         The blob should contain the user's signal encryption keys encrypted
    ///         to their wallet public key.
    /// @dev Gated by whenNotPaused so emergency-pause halts new writes (including
    ///      griefing/poison blobs). Reads stay unguarded so users can still recover
    ///      during a pause window. MAINNET_BLOCKERS P1-27.
    /// @param blob The encrypted recovery blob
    function storeRecoveryBlob(bytes calldata blob) external whenNotPaused {
        if (blob.length == 0) revert EmptyBlob();
        if (blob.length > MAX_BLOB_SIZE) revert BlobTooLarge(blob.length, MAX_BLOB_SIZE);

        _recoveryBlobs[msg.sender] = blob;

        emit RecoveryBlobStored(msg.sender, block.timestamp);
    }

    /// @notice Retrieve the stored recovery blob for a given user address.
    ///         The blob is encrypted, so reading it reveals nothing without
    ///         the user's wallet private key.
    /// @dev Intentionally NOT whenNotPaused: users must always be able to pull
    ///      their encrypted blob for recovery, even during an emergency pause.
    /// @param user The wallet address to look up
    /// @return The encrypted recovery blob (empty bytes if none stored)
    function getRecoveryBlob(address user) external view returns (bytes memory) {
        return _recoveryBlobs[user];
    }

    // -------------------------------------------------------------------------
    // Emergency pause
    // -------------------------------------------------------------------------

    /// @notice Set the emergency pauser address
    /// @param _pauser New pauser address (address(0) to disable pauser-triggered pause;
    ///                owner can always still pause)
    function setPauser(address _pauser) external onlyOwner {
        pauser = _pauser;
        emit PauserUpdated(_pauser);
    }

    /// @notice Pause recovery-blob writes
    function pause() external {
        if (msg.sender != pauser && msg.sender != owner()) revert NotPauserOrOwner(msg.sender);
        _pause();
    }

    /// @notice Unpause recovery-blob writes (owner / timelock only)
    function unpause() external onlyOwner {
        _unpause();
    }

    // -------------------------------------------------------------------------
    // Upgrade Authorization
    // -------------------------------------------------------------------------

    /// @dev UUPS authorization: only the owner (timelock) can upgrade the impl.
    function _authorizeUpgrade(address) internal override onlyOwner {}
}
