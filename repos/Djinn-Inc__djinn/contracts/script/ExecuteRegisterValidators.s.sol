// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title ExecuteRegisterValidators
/// @notice Executes the validator-registration batch previously scheduled by
///         ScheduleRegisterValidators.s.sol. Supply the SAME VALIDATOR_1..N
///         env vars in the same order as the schedule run, otherwise the batch
///         ID won't match.
contract ExecuteRegisterValidators is Script {
    bytes32 constant BOOTSTRAP_SALT = keccak256("register-validators-bootstrap");

    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address deployer = vm.addr(deployerKey);
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        address[] memory validators = _collectValidators();
        require(validators.length >= 3, "need at least 3 validators (MIN_VALIDATORS)");

        address[] memory targets = new address[](validators.length);
        uint256[] memory values = new uint256[](validators.length);
        bytes[] memory payloads = new bytes[](validators.length);

        for (uint256 i = 0; i < validators.length; i++) {
            targets[i] = OUTCOME_VOTING_PROXY;
            values[i] = 0;
            payloads[i] = abi.encodeCall(OutcomeVoting.addValidator, (validators[i]));
        }

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), BOOTSTRAP_SALT);
        console.log("Deployer:", deployer);
        console.log("Batch ID:");
        console.logBytes32(batchId);
        console.log("isOperationReady:", timelock.isOperationReady(batchId));

        vm.startBroadcast(deployerKey);
        timelock.executeBatch(targets, values, payloads, bytes32(0), BOOTSTRAP_SALT);
        vm.stopBroadcast();

        console.log("");
        console.log("=== VALIDATOR REGISTRATION EXECUTED ===");
        console.log("Registered validators:", validators.length);
        for (uint256 i = 0; i < validators.length; i++) {
            console.log("  validator", i + 1, ":", validators[i]);
        }
        console.log("");
        console.log("Verify on-chain:");
        console.log("  cast call", OUTCOME_VOTING_PROXY, '"validatorCount()(uint256)"');
    }

    function _collectValidators() internal view returns (address[] memory out) {
        address[] memory buf = new address[](10);
        uint256 n = 0;
        for (uint256 i = 1; i <= 10; i++) {
            string memory key = string.concat("VALIDATOR_", vm.toString(i));
            try vm.envAddress(key) returns (address v) {
                if (v != address(0)) {
                    buf[n++] = v;
                }
            } catch {
                // env var not set; skip
            }
        }
        out = new address[](n);
        for (uint256 i = 0; i < n; i++) {
            out[i] = buf[i];
        }
    }
}
