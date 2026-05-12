// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

import {CreditLedger} from "../src/CreditLedger.sol";
import {SignalCommitment} from "../src/SignalCommitment.sol";

/// @title ExecuteWireMissingSetters
/// @notice Execute the batch scheduled by ScheduleWireMissingSetters. Salt
///         + targets + payloads must match exactly.
contract ExecuteWireMissingSetters is Script {
    bytes32 constant SALT = keccak256("wire-missing-setters-p1-17-p1-19");

    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;
    address constant CREDIT_LEDGER = 0xA65296cd11B65629641499024AD905FAcAB64C3E;
    address constant SIGNAL_COMMITMENT = 0x4712479Ba57c9ED40405607b2B18967B359209C0;
    address constant COLLATERAL = 0x71F0a8c6BBFc4C83c5203807fAdd305B0C0F4C88;
    address constant PAUSER = 0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address deployer = vm.addr(deployerKey);
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        address[] memory targets = new address[](2);
        uint256[] memory values = new uint256[](2);
        bytes[] memory payloads = new bytes[](2);

        targets[0] = CREDIT_LEDGER;
        values[0] = 0;
        payloads[0] = abi.encodeCall(CreditLedger.setPauser, (PAUSER));

        targets[1] = SIGNAL_COMMITMENT;
        values[1] = 0;
        payloads[1] = abi.encodeCall(SignalCommitment.setCollateral, (COLLATERAL));

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);
        console.log("Deployer:", deployer);
        console.log("Batch ID:");
        console.logBytes32(batchId);
        console.log("isOperationReady:", timelock.isOperationReady(batchId));

        vm.startBroadcast(deployerKey);
        timelock.executeBatch(targets, values, payloads, bytes32(0), SALT);
        vm.stopBroadcast();

        console.log("");
        console.log("=== WIRE-MISSING-SETTERS EXECUTED ===");
        console.log("Verify on-chain:");
        console.log("  cast call", CREDIT_LEDGER, '"pauser()(address)"');
        console.log("  cast call", SIGNAL_COMMITMENT, '"collateral()(address)"');
    }
}
