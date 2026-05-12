// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/// @title ExecuteUpgradeAccountDropOutcomeCheck
/// @notice Executes the v1617 Account upgrade after timelock delay.
contract ExecuteUpgradeAccountDropOutcomeCheck is Script {
    bytes32 constant SALT = keccak256("account-drop-outcome-check-v1617-paused-2026-04-27");

    address constant ACCOUNT_PROXY = 0x4546354Dd32a613B76Abf530F81c8359e7cE440B;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 executorKey = vm.envUint("DEPLOYER_KEY");
        address acctImpl = vm.envAddress("ACCT_IMPL_DROP_OUTCOME");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Executor:", vm.addr(executorKey));
        console.log("Account impl (v1617):", acctImpl);

        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        targets[0] = ACCOUNT_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        targets[1] = ACCOUNT_PROXY;
        payloads[1] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (acctImpl, ""));

        targets[2] = ACCOUNT_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);
        require(timelock.isOperationReady(batchId), "Batch not ready");

        vm.startBroadcast(executorKey);
        timelock.executeBatch(targets, values, payloads, bytes32(0), SALT);
        vm.stopBroadcast();

        console.log("Account v1617 executed. Batch ID:");
        console.logBytes32(batchId);
    }
}
