// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

/// @title UpdateTimelockDelay
/// @notice Schedules a one-shot operation that changes the testnet
///         TimelockController's minDelay from 72 hours to 72 seconds.
///
///         How it works:
///           - TimelockController.updateDelay() can only be called by the
///             timelock itself (msg.sender == address(this)). The only way
///             to do that is to schedule it as a normal timelock operation
///             and execute it after the current minDelay elapses.
///           - We schedule one operation: target = TIMELOCK, payload =
///             updateDelay(72). It uses the CURRENT delay (72h) as its
///             own wait period, because that's what the contract enforces.
///           - After 72 hours we run ExecuteTimelockDelayUpdate.s.sol
///             (or anyone does — executor == address(0) allows public
///             execution) and the timelock's minDelay becomes 72 seconds
///             for all future operations.
///
///         Rationale: testnet needs rapid dev iteration. The 72h wait on
///         every schedule+execute cycle is burning weeks of cumulative
///         wall-clock time for changes with no real money at risk. This
///         operation pays the 72h cost one final time so future testnet
///         upgrades are ~72 seconds each. Mainnet deploys from Deploy.s.sol
///         still get the full 72h because the chain-conditional check
///         there is independent of this one-shot.
///
///         Usage:
///           forge script script/UpdateTimelockDelay.s.sol \
///             --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
///
///         After 72h:
///           forge script script/ExecuteTimelockDelayUpdate.s.sol \
///             --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
contract UpdateTimelockDelay is Script {
    /// Fixed testnet TimelockController address. Owner of all 7 UUPS proxies.
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    /// Target new delay: 72 seconds. Fast enough that dev iteration doesn't
    /// feel like bureaucracy, long enough that a buggy schedule can still
    /// be cancelled by the proposer before it lands.
    uint256 constant NEW_DELAY_SECONDS = 72;

    /// Salt lets us uniquely identify this specific operation in timelock
    /// events and scripts. Not security-critical.
    bytes32 constant UPDATE_SALT = keccak256("testnet-minDelay-72s-2026-04-11");

    function run() external {
        // Guard: only run this on testnet. Mainnet deploys should keep 72h.
        require(
            block.chainid == 84_532 || block.chainid == 31_337,
            "UpdateTimelockDelay: only run on Base Sepolia (84532) or local (31337)"
        );

        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address deployer = vm.addr(deployerKey);
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", deployer);
        console.log("Chain ID:", block.chainid);
        console.log("Timelock:", TIMELOCK);
        console.log("");

        // Read current delay to confirm we're starting from the expected state.
        uint256 currentDelay = timelock.getMinDelay();
        console.log("Current minDelay (seconds):", currentDelay);
        console.log("Target minDelay (seconds):", NEW_DELAY_SECONDS);
        console.log("");

        require(currentDelay != NEW_DELAY_SECONDS, "UpdateTimelockDelay: already at target delay, nothing to do");

        // Build the single-operation schedule.
        //   target = timelock itself (only address allowed to call updateDelay)
        //   value  = 0 (no ETH transfer)
        //   payload = abi.encodeCall(updateDelay(NEW_DELAY_SECONDS))
        //   predecessor = bytes32(0) (no dependency on a prior scheduled op)
        //   salt = UPDATE_SALT
        //   delay = currentDelay (the op must wait the CURRENT minDelay before
        //           becoming executable, which is exactly what we want)

        address target = TIMELOCK;
        uint256 value = 0;
        bytes memory payload = abi.encodeCall(TimelockController.updateDelay, (NEW_DELAY_SECONDS));

        vm.startBroadcast(deployerKey);
        timelock.schedule(target, value, payload, bytes32(0), UPDATE_SALT, currentDelay);
        vm.stopBroadcast();

        bytes32 operationId = timelock.hashOperation(target, value, payload, bytes32(0), UPDATE_SALT);

        uint256 executableAt = block.timestamp + currentDelay;

        console.log("Operation scheduled.");
        console.log("Operation ID:");
        console.logBytes32(operationId);
        console.log("");
        console.log("Executable at timestamp:", executableAt);
        console.log("Approx wall clock:", executableAt);
        console.log("(human time via `date -r` or a calendar tool)");
        console.log("");
        console.log("To execute after the delay expires:");
        console.log("  forge script script/ExecuteTimelockDelayUpdate.s.sol \\");
        console.log("    --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast");
        console.log("");
        console.log("Monitor via scripts/timelock-monitor.sh (already watching this timelock).");
    }
}
