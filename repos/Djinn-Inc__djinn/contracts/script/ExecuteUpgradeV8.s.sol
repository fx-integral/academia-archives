// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import {SignalCommitment} from "../src/SignalCommitment.sol";

/// @title ExecuteUpgradeV8
/// @notice Executes the V8 SignalCommitment upgrade (P1-28) after the timelock
///         delay has elapsed. Verifies the ERC-1967 implementation slot.
///
/// Required env vars (from ScheduleUpgradeV8 output):
///   SIGNAL_COMMITMENT_IMPL_V8
///
/// Usage:
///   forge script script/ExecuteUpgradeV8.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
contract ExecuteUpgradeV8 is Script {
    bytes32 constant UPGRADE_SALT = keccak256("v8-signalcommitment-cancel-whenNotPaused");

    address constant SIGNAL_COMMITMENT_PROXY = 0x4712479Ba57c9ED40405607b2B18967B359209C0;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address scImpl = vm.envAddress("SIGNAL_COMMITMENT_IMPL_V8");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("SignalCommitment impl V8:", scImpl);

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

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), UPGRADE_SALT);
        console.log("Batch ID:");
        console.logBytes32(batchId);

        bool ready = timelock.isOperationReady(batchId);
        bool pending = timelock.isOperationPending(batchId);
        console.log("Operation pending:", pending);
        console.log("Operation ready:", ready);

        require(ready, "Not ready (delay not elapsed or not scheduled)");

        vm.startBroadcast(deployerKey);
        timelock.executeBatch(targets, values, payloads, bytes32(0), UPGRADE_SALT);
        vm.stopBroadcast();

        bytes32 implSlot = bytes32(uint256(keccak256("eip1967.proxy.implementation")) - 1);
        address actual = address(uint160(uint256(vm.load(SIGNAL_COMMITMENT_PROXY, implSlot))));

        console.log("");
        console.log("=== POST-UPGRADE VERIFICATION ===");
        console.log("SignalCommitment");
        console.log("  Expected:", scImpl);
        console.log("  Actual:", actual);
        console.log("  Match:", actual == scImpl);
        require(actual == scImpl, "Implementation mismatch");

        console.log("");
        console.log("V8 upgrade executed. SignalCommitment proxy verified.");
    }
}
