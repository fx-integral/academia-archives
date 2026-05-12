// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

import {CreditLedger} from "../src/CreditLedger.sol";
import {SignalCommitment} from "../src/SignalCommitment.sol";

/// @title ScheduleWireMissingSetters
/// @notice Close P1-17 + P1-19 on the current Sepolia deployment without a
///         full redeploy. Deploy.s.sol shipped the fixes (v1340-ish: commits
///         98d8ec66 + 29434d0c) but the already-deployed proxies on Base
///         Sepolia still show CreditLedger.pauser()=0x0 and
///         SignalCommitment.collateral()=0x0. This script schedules the two
///         missing setter calls as a single timelock batch.
///
/// Usage:
///   DEPLOYER_KEY=0x... forge script script/ScheduleWireMissingSetters.s.sol \
///     --rpc-url https://sepolia.base.org --broadcast
///
///   wait TimelockController.getMinDelay() (72s on Sepolia), then run
///   ExecuteWireMissingSetters.s.sol with the same DEPLOYER_KEY.
contract ScheduleWireMissingSetters is Script {
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

        uint256 delay = timelock.getMinDelay();

        console.log("Deployer:", deployer);
        console.log("Chain ID:", block.chainid);
        console.log("Timelock delay (seconds):", delay);
        console.log("Target 0 (CreditLedger):", targets[0]);
        console.log("  setPauser(", PAUSER, ")");
        console.log("Target 1 (SignalCommitment):", targets[1]);
        console.log("  setCollateral(", COLLATERAL, ")");

        vm.startBroadcast(deployerKey);
        timelock.scheduleBatch(targets, values, payloads, bytes32(0), SALT, delay);
        vm.stopBroadcast();

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);

        console.log("");
        console.log("=== WIRE-MISSING-SETTERS SCHEDULED ===");
        console.log("Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after timestamp:", block.timestamp + delay);
    }
}
