// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title ScheduleUpgradeOVDeriveEarlyExit
/// @notice v1616 P0-01 long-term fix. Deploys an OutcomeVoting impl that
///         drops the validator-supplied `isEarlyExit` from scoreHash and
///         derives it deterministically from `purchaseIds.length <
///         MIN_BATCH_SIZE`. Also exposes resetBatchVotes(bytes32) for
///         recovery (votes-only reset that preserves consent).
///
/// On-chain evidence (2026-04-27): (G0, 0x5b8d, [472..475]) batch shows
///   - hasVoted: UIDs 0/1/2 = true, UIDs 86/213 = false
///   - voteCounts split 2 (isEarlyExit=false) + 1 (isEarlyExit=true)
///   - threshold = 3, neither bucket reached → finalized=false forever
/// Same divergence pattern across the fleet has produced zero AuditSettled
/// events in 8+ days despite v1609..v1615 fixes that all chased downstream
/// layers (BatchTooSmall revert, principal/credits invariant, mark_settled
/// timing, fan-out targeting). The actual fix is in OV.submitVote.
contract ScheduleUpgradeOVDeriveEarlyExit is Script {
    bytes32 constant SALT = keccak256("ov-derive-early-exit-v1616-2026-04-27");

    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Chain ID:", block.chainid);

        vm.startBroadcast(deployerKey);
        address ovImpl = address(new OutcomeVoting());
        console.log("New OV impl (v1616):", ovImpl);

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

        console.log("OV v1616 derive-early-exit upgrade scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after (unix ts):", block.timestamp + delay);
        console.log("Delay (seconds):", delay);
        console.log("");
        console.log("Add to .env for ExecuteUpgradeOVDeriveEarlyExit:");
        console.log("  OV_IMPL_DERIVE_EE=", ovImpl);
    }
}
