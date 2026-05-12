// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/// @title ExecuteUpgradeOVRequestEarlyExitSort
/// @notice Executes the OV requestEarlyExit-sort fix batch after the
///         timelock delay has elapsed. Pairs with
///         ScheduleUpgradeOVRequestEarlyExitSort.
contract ExecuteUpgradeOVRequestEarlyExitSort is Script {
    bytes32 constant SALT = keccak256("ov-requestEarlyExit-sort-2026-04-26");

    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 executorKey = vm.envUint("DEPLOYER_KEY");
        address ovImpl = vm.envAddress("OV_IMPL_REE_SORT");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Executor:", vm.addr(executorKey));
        console.log("OV impl:", ovImpl);

        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        targets[0] = OUTCOME_VOTING_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        targets[1] = OUTCOME_VOTING_PROXY;
        payloads[1] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (ovImpl, ""));

        targets[2] = OUTCOME_VOTING_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);
        require(timelock.isOperationReady(batchId), "Batch not ready");

        vm.startBroadcast(executorKey);
        timelock.executeBatch(targets, values, payloads, bytes32(0), SALT);
        vm.stopBroadcast();

        console.log("OV requestEarlyExit-sort upgrade executed. Batch ID:");
        console.logBytes32(batchId);
    }
}
