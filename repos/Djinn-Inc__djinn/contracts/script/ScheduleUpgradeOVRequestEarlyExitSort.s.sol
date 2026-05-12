// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title ScheduleUpgradeOVRequestEarlyExitSort
/// @notice Deploys an OutcomeVoting impl that adds the strictly-ascending
///         purchaseIds enforcement to `requestEarlyExit`, then schedules
///         the pause → upgrade → unpause batch via the TimelockController.
///
/// What this fixes (found 2026-04-26 fresh-eyes audit on Audit V2):
/// - `submitVote` already requires purchaseIds in strictly ascending order
///   (line 494) so all validator-driven settlement reads/writes the
///   canonical sorted batchKey.
/// - `requestEarlyExit` accepted ANY order. A frontend or party that calls
///   it with insertion-order (or any non-sorted) IDs writes
///   `earlyExitRequested[unsortedKey]=true`, but validators submit votes
///   at `sortedKey`, so the consent flag is never read.
/// - Net effect: silent consent failure. The Audit V2 precondition
///   (`_validateEarlyExitPermitted`) reverts with EarlyExitNotPermitted,
///   the only remaining settlement path is the 45-day timeout, and a
///   hanging flag at the unsorted key cannot be cleared.
///
/// Fix: mirror the sort check from submitVote in requestEarlyExit. Existing
/// opt-ins from sorted callers (e.g., G0's call for stuck batch [472,473,
/// 474,475] tx 0xbb8b0e65) are unaffected because the storage key is
/// derived from the same canonical sort.
///
/// Usage:
///   forge script script/ScheduleUpgradeOVRequestEarlyExitSort.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL \
///     --broadcast
contract ScheduleUpgradeOVRequestEarlyExitSort is Script {
    bytes32 constant SALT = keccak256("ov-requestEarlyExit-sort-2026-04-26");

    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Chain ID:", block.chainid);

        vm.startBroadcast(deployerKey);
        address ovImpl = address(new OutcomeVoting());
        console.log("New OV impl:", ovImpl);

        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        targets[0] = OUTCOME_VOTING_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        targets[1] = OUTCOME_VOTING_PROXY;
        payloads[1] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (ovImpl, ""));

        targets[2] = OUTCOME_VOTING_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

        uint256 delay = timelock.getMinDelay();
        timelock.scheduleBatch(targets, values, payloads, bytes32(0), SALT, delay);

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);
        vm.stopBroadcast();

        console.log("OV requestEarlyExit-sort upgrade scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after (unix ts):", block.timestamp + delay);
        console.log("Delay (seconds):", delay);
        console.log("");
        console.log("Add to .env for ExecuteUpgradeOVRequestEarlyExitSort:");
        console.log("  OV_IMPL_REE_SORT=", ovImpl);
    }
}
