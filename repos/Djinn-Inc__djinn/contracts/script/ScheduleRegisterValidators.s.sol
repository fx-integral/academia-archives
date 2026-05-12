// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title ScheduleRegisterValidators
/// @notice Bootstrap the OutcomeVoting validator set. At deploy time,
///         validatorCount()=0 so no settlement can complete (every submitVote
///         reverts with NotValidator). This script schedules addValidator(eoa)
///         calls through the TimelockController for N validator EOAs provided
///         via env vars.
///
///         MIN_VALIDATORS=3 is a hardcoded constant in OutcomeVoting.sol, so
///         at least 3 addresses must be scheduled. Supply up to 10 (VALIDATOR_1
///         through VALIDATOR_10). Omitted slots are skipped.
///
/// Usage:
///   export VALIDATOR_1=0x...
///   export VALIDATOR_2=0x...
///   export VALIDATOR_3=0x...
///   forge script script/ScheduleRegisterValidators.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
///
///   wait TimelockController.getMinDelay() seconds, then:
///   forge script script/ExecuteRegisterValidators.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
contract ScheduleRegisterValidators is Script {
    bytes32 constant BOOTSTRAP_SALT = keccak256("register-validators-bootstrap");

    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address deployer = vm.addr(deployerKey);
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        address[] memory validators = _collectValidators();
        require(validators.length >= 3, "need at least 3 validators (MIN_VALIDATORS)");

        console.log("Deployer:", deployer);
        console.log("Chain ID:", block.chainid);
        console.log("Validator count to register:", validators.length);
        for (uint256 i = 0; i < validators.length; i++) {
            console.log("  validator", i + 1, ":", validators[i]);
        }
        console.log("");

        address[] memory targets = new address[](validators.length);
        uint256[] memory values = new uint256[](validators.length);
        bytes[] memory payloads = new bytes[](validators.length);

        for (uint256 i = 0; i < validators.length; i++) {
            targets[i] = OUTCOME_VOTING_PROXY;
            values[i] = 0;
            payloads[i] = abi.encodeCall(OutcomeVoting.addValidator, (validators[i]));
        }

        uint256 delay = timelock.getMinDelay();
        console.log("Timelock delay (seconds):", delay);

        vm.startBroadcast(deployerKey);
        timelock.scheduleBatch(targets, values, payloads, bytes32(0), BOOTSTRAP_SALT, delay);
        vm.stopBroadcast();

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), BOOTSTRAP_SALT);

        console.log("");
        console.log("=== VALIDATOR REGISTRATION SCHEDULED ===");
        console.log("Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after timestamp:", block.timestamp + delay);
        console.log("");
        console.log("Next: set REGISTER_VALIDATORS env vars identically and run");
        console.log("      ExecuteRegisterValidators.s.sol after the delay.");
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
