// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title ScheduleUpgradeOVShareRecovery
/// @notice Deploys a new OutcomeVoting implementation that adds Phase 1 of
///         the C+F share recovery design (project_share_recovery_design_2026_05_03.md)
///         and schedules pause -> upgrade -> unpause via TimelockController.
///
/// What this upgrade adds (additive only):
/// - storage: mapping(address => bytes32) public encryptionPubkey
/// - event: EncryptionPubkeyUpdated(address indexed signer, bytes32 pubkey)
/// - function: setEncryptionPubkey(bytes32) callable by registered validators
/// - constant: FEATURE_SHARE_RECOVERY = keccak256("SHARE_RECOVERY")
/// - view: supportsFeature(bytes32) returns true for FEATURE_SHARE_RECOVERY
/// - __gap reduced 31 -> 30
///
/// Default post-upgrade behavior unchanged: validators must explicitly call
/// setEncryptionPubkey(...) before geniuses will use the new bundle fan-out
/// path. Until they do, encryptionPubkey[v] returns bytes32(0) and the
/// genius client falls back to skipping that validator (with retry on
/// subsequent signals).
///
/// Usage:
///   forge script script/ScheduleUpgradeOVShareRecovery.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL \
///     --broadcast
contract ScheduleUpgradeOVShareRecovery is Script {
    bytes32 constant SALT = keccak256("outcome-voting-share-recovery-phase1");

    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Chain ID:", block.chainid);

        vm.startBroadcast(deployerKey);
        address ovImpl = address(new OutcomeVoting());
        console.log("New OutcomeVoting impl:", ovImpl);

        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        targets[0] = OUTCOME_VOTING_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        targets[1] = OUTCOME_VOTING_PROXY;
        payloads[1] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (ovImpl, ""));

        targets[2] = OUTCOME_VOTING_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

        uint256 delay = timelock.getMinDelay();
        timelock.scheduleBatch(targets, values, payloads, bytes32(0), SALT, delay);

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);
        vm.stopBroadcast();

        console.log("OV ShareRecovery upgrade scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after:", block.timestamp + delay);
        console.log("Delay (seconds):", delay);
        console.log("");
        console.log("Add to .env for ExecuteUpgradeOVShareRecovery:");
        console.log("  OV_IMPL_SHARE_RECOVERY=", ovImpl);
    }
}
