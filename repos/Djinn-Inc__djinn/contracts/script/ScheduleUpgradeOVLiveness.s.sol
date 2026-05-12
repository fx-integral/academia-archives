// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title ScheduleUpgradeOVLiveness
/// @notice Deploys a new OutcomeVoting implementation that adds P0-11
///         Milestone 1 (liveness-aware quorum) and schedules the
///         pause → upgrade → unpause batch via the TimelockController.
///
/// What this upgrade adds:
/// - `lastActiveBlock[validator]` — block of last vote/heartbeat
/// - `activeWindow` — block window for "active" status (0 = feature off)
/// - `heartbeat()` — ping to stay in denominator during dry spells
/// - `activeCount()` / `isActive(address)` — views
/// - `submitVote` / `quorumThreshold` snapshot active count (floored
///   at MIN_VALIDATORS=3) when activeWindow > 0
///
/// Default post-upgrade behavior is unchanged (activeWindow=0, legacy).
/// To activate: schedule+execute a separate `setActiveWindow(1800)` via
/// timelock. Recommended on Base (~2s blocks): 1800 blocks ≈ 1h.
///
/// Simplification note: this upgrade was briefly scoped to include vote
/// bonding (M2) and oracle fraud-proof slashing (M3) but those were
/// reverted in v1603 as speculative defenses redundant with Bittensor's
/// native stake-slashing via Yuma consensus. If a real fraud event
/// ever materializes, a future UUPS upgrade can add slashing.
///
/// Usage:
///   forge script script/ScheduleUpgradeOVLiveness.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL \
///     --broadcast
contract ScheduleUpgradeOVLiveness is Script {
    bytes32 constant SALT = keccak256("outcome-voting-liveness-m1");

    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Chain ID:", block.chainid);

        vm.startBroadcast(deployerKey);
        address ovImpl = address(new OutcomeVoting());
        console.log("New OutcomeVoting impl:", ovImpl);

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

        console.log("OV Liveness upgrade scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after:", block.timestamp + delay);
        console.log("Delay (seconds):", delay);
        console.log("");
        console.log("Add to .env for ExecuteUpgradeOVLiveness:");
        console.log("  OV_IMPL_LIVENESS=", ovImpl);
    }
}
