// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Account as DjinnAccount} from "../src/Account.sol";

/// @title ScheduleUpgradeAccountDropOutcomeCheck
/// @notice v1617 P0-01 layer 2 fix. Deploys Account impl that removes the
///         per-purchase outcome check from markBatchAudited. The OV quorum
///         (2/3+ validators) is the trust source for batch validity in V2.
contract ScheduleUpgradeAccountDropOutcomeCheck is Script {
    bytes32 constant SALT = keccak256("account-drop-outcome-check-v1617-paused-2026-04-27");

    address constant ACCOUNT_PROXY = 0x4546354Dd32a613B76Abf530F81c8359e7cE440B;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Chain ID:", block.chainid);

        vm.startBroadcast(deployerKey);
        address acctImpl = address(new DjinnAccount());
        console.log("New Account impl (v1617):", acctImpl);

        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        targets[0] = ACCOUNT_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        targets[1] = ACCOUNT_PROXY;
        payloads[1] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (acctImpl, ""));

        targets[2] = ACCOUNT_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

        uint256 delay = timelock.getMinDelay();
        timelock.scheduleBatch(targets, values, payloads, bytes32(0), SALT, delay);

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);
        vm.stopBroadcast();

        console.log("Account v1617 upgrade scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after (unix ts):", block.timestamp + delay);
        console.log("Add to .env: ACCT_IMPL_DROP_OUTCOME=", acctImpl);
    }
}
