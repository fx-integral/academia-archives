// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title AddValidatorSigner
/// @notice Schedules a single OutcomeVoting.addValidator(SIGNER) call through
///         TimelockController. Unlike ScheduleRegisterValidators which
///         bootstraps from zero (and has a >=3 requirement), this script is
///         for incremental additions after the set is live.
///
///         Uses a salt derived from the signer address so repeated runs for
///         different signers don't collide, and a re-run for the same signer
///         will idempotently hit the same operation ID (handy if a prior run
///         failed to broadcast).
///
/// Usage:
///   export SIGNER=0x26A766aFA20867ff047F5029177Da58b96547f77
///   forge script script/AddValidatorSigner.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
///
///   wait getMinDelay() seconds, then execute:
///   cast send 0x37f41E... "execute(address,uint256,bytes,bytes32,bytes32)" \
///     0xAD534f... 0 $PAYLOAD 0x0 $SALT --rpc-url $RPC
contract AddValidatorSigner is Script {
    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address signer = vm.envAddress("SIGNER");
        require(signer != address(0), "SIGNER must be set");

        TimelockController timelock = TimelockController(payable(TIMELOCK));
        bytes32 salt = keccak256(abi.encode("add-validator", signer));
        bytes memory payload = abi.encodeCall(OutcomeVoting.addValidator, (signer));

        uint256 delay = timelock.getMinDelay();
        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Signer to add:", signer);
        console.log("Timelock delay (seconds):", delay);

        vm.startBroadcast(deployerKey);
        timelock.schedule(OUTCOME_VOTING_PROXY, 0, payload, bytes32(0), salt, delay);
        vm.stopBroadcast();

        bytes32 opId = timelock.hashOperation(OUTCOME_VOTING_PROXY, 0, payload, bytes32(0), salt);
        console.log("");
        console.log("=== SCHEDULED ===");
        console.log("Operation ID:");
        console.logBytes32(opId);
        console.log("Executable after timestamp:", block.timestamp + delay);
        console.log("");
        console.log("Payload:");
        console.logBytes(payload);
        console.log("Salt:");
        console.logBytes32(salt);
    }
}
