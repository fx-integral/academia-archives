// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import {SignalCommitment} from "../src/SignalCommitment.sol";

/// @title ScheduleUpgradeV8
/// @notice Schedules a 3-operation timelock batch to close MAINNET_BLOCKERS P1-28:
///         pause → upgradeToAndCall → unpause on the SignalCommitment proxy.
///
///         V8 adds the `whenNotPaused` guard to `SignalCommitment.cancelSignal`
///         (source v1321). The fix is in the source; this script ships the
///         impl on-chain and atomically flips the proxy to it.
///
///         After the timelock delay, run ExecuteUpgradeV8.s.sol.
///
///         KeyRecovery (P1-27) is intentionally NOT included. The live KR at
///         0x496919DB9BC4590323cd019fE874311AC6116525 is the bare
///         non-upgradable v1 contract (verified 2026-04-19: code size 2177B,
///         owner() reverts, ERC-1967 impl slot == 0x0). Closing P1-27 requires
///         a fresh UUPS deploy (P1-18 prerequisite) with a blob-migration plan
///         for existing users — tracked separately.
///
/// Usage:
///   forge script script/ScheduleUpgradeV8.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
contract ScheduleUpgradeV8 is Script {
    bytes32 constant UPGRADE_SALT = keccak256("v8-signalcommitment-cancel-whenNotPaused");

    address constant SIGNAL_COMMITMENT_PROXY = 0x4712479Ba57c9ED40405607b2B18967B359209C0;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address deployer = vm.addr(deployerKey);
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", deployer);
        console.log("Chain ID:", block.chainid);
        console.log("");

        vm.startBroadcast(deployerKey);

        address scImpl = address(new SignalCommitment());

        console.log("New implementation deployed:");
        console.log("  SignalCommitment impl:", scImpl);
        console.log("");

        // 3-op batch: pause → upgradeToAndCall → unpause
        uint256 opCount = 3;
        address[] memory targets = new address[](opCount);
        uint256[] memory values = new uint256[](opCount);
        bytes[] memory payloads = new bytes[](opCount);

        targets[0] = SIGNAL_COMMITMENT_PROXY;
        payloads[0] = abi.encodeCall(SignalCommitment.pause, ());

        targets[1] = SIGNAL_COMMITMENT_PROXY;
        payloads[1] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (scImpl, ""));

        targets[2] = SIGNAL_COMMITMENT_PROXY;
        payloads[2] = abi.encodeCall(SignalCommitment.unpause, ());

        uint256 delay = timelock.getMinDelay();
        console.log("Timelock delay (seconds):", delay);

        timelock.scheduleBatch(targets, values, payloads, bytes32(0), UPGRADE_SALT, delay);

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), UPGRADE_SALT);

        vm.stopBroadcast();

        console.log("V8 batch scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after timestamp:", block.timestamp + delay);
        console.log("");

        console.log("=== UPGRADE SCHEDULED (V8: cancelSignal whenNotPaused) ===");
        console.log("Proxy (unchanged after upgrade):");
        console.log("  SignalCommitment:", SIGNAL_COMMITMENT_PROXY);
        console.log("");
        console.log("Set this env var for ExecuteUpgradeV8.s.sol:");
        console.log("  SIGNAL_COMMITMENT_IMPL_V8=", scImpl);
    }
}
