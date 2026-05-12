// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

/// @title ExecuteTimelockDelayUpdate
/// @notice Companion to UpdateTimelockDelay.s.sol. Executes the previously
///         scheduled updateDelay(72) operation once the 72h window has
///         elapsed. Any address can call this because the timelock was
///         deployed with executor = address(0) (public execution).
///
///         Usage (run ~72h after scheduling):
///           forge script script/ExecuteTimelockDelayUpdate.s.sol \
///             --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
contract ExecuteTimelockDelayUpdate is Script {
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;
    uint256 constant NEW_DELAY_SECONDS = 72;
    bytes32 constant UPDATE_SALT = keccak256("testnet-minDelay-72s-2026-04-11");

    function run() external {
        require(
            block.chainid == 84_532 || block.chainid == 31_337,
            "ExecuteTimelockDelayUpdate: only run on Base Sepolia or local"
        );

        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        address target = TIMELOCK;
        uint256 value = 0;
        bytes memory payload = abi.encodeCall(TimelockController.updateDelay, (NEW_DELAY_SECONDS));

        bytes32 operationId = timelock.hashOperation(target, value, payload, bytes32(0), UPDATE_SALT);

        console.log("Operation ID:");
        console.logBytes32(operationId);

        // Sanity check: is the operation ready?
        require(
            timelock.isOperationReady(operationId),
            "ExecuteTimelockDelayUpdate: operation not ready yet (either not scheduled or delay not elapsed)"
        );
        require(!timelock.isOperationDone(operationId), "ExecuteTimelockDelayUpdate: operation already executed");

        uint256 beforeDelay = timelock.getMinDelay();
        console.log("minDelay before:", beforeDelay);

        vm.startBroadcast(deployerKey);
        timelock.execute(target, value, payload, bytes32(0), UPDATE_SALT);
        vm.stopBroadcast();

        uint256 afterDelay = timelock.getMinDelay();
        console.log("minDelay after:", afterDelay);
        require(afterDelay == NEW_DELAY_SECONDS, "ExecuteTimelockDelayUpdate: post-condition check failed");

        console.log("");
        console.log("Done. Testnet timelock is now at 72 seconds.");
        console.log("Future scheduled operations will be executable after ~72s instead of 72h.");
    }
}
