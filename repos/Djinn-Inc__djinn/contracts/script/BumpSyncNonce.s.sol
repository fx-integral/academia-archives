// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title BumpSyncNonce
/// @notice Unsticks a jammed `proposeSync` cycle by scheduling
///         removeValidator(target) followed by addValidator(target) on a
///         single OV signer. Each call increments `syncNonce`, clearing
///         the per-signer `hasSyncVoted[oldNonce][...]=true` state that
///         blocks any new proposal from converging to quorum.
///
///         Discovered 2026-05-01 via `cast run` on reverted signer txs:
///         all 5 OV signers had `hasSyncVoted[11]=true` on different
///         4-validator subsets (each operator's metagraph excluded a
///         different transient peer), so no proposal hash got 4/5 quorum
///         and submitVote was perpetually gated on a stable validator
///         set. AuditSettled 28h count = 0 across weeks because of this.
///
///         **Prerequisite:** ALL operators MUST be running validator
///         v1640 or later (additions-only sync). Otherwise after this
///         script bumps syncNonce, operators on older code will re-jam
///         the new nonce by proposing different subsets again. Verify
///         each operator's `/health.version` reads 1640+ before running.
///
/// Usage:
///   export SIGNER=0xfae35E00b23e5CF8D4A4E5bc4f5b397b4522cA86  # any signer
///   forge script script/BumpSyncNonce.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
///   # wait getMinDelay() seconds (~72s testnet)
///   # execute remove via timelock.execute(...)
///   # then re-run this script to schedule addValidator (commented step)
///   # wait + execute add
contract BumpSyncNonce is Script {
    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address signer = vm.envAddress("SIGNER");
        require(signer != address(0), "SIGNER must be set");

        TimelockController timelock = TimelockController(payable(TIMELOCK));

        // Schedule the REMOVE first. Salt includes a "bump" tag and
        // current syncNonce so a re-run after a partial completion
        // doesn't collide with a prior schedule.
        OutcomeVoting ov = OutcomeVoting(OUTCOME_VOTING_PROXY);
        uint256 currentNonce = ov.syncNonce();
        console.log("Current syncNonce:", currentNonce);

        bytes32 removeSalt = keccak256(abi.encode("bump-sync-remove", signer, currentNonce));
        bytes memory removePayload = abi.encodeCall(OutcomeVoting.removeValidator, (signer));

        uint256 delay = timelock.getMinDelay();
        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Target signer:", signer);
        console.log("Timelock delay (seconds):", delay);

        vm.startBroadcast(deployerKey);
        timelock.schedule(OUTCOME_VOTING_PROXY, 0, removePayload, bytes32(0), removeSalt, delay);
        vm.stopBroadcast();

        bytes32 removeOpId = timelock.hashOperation(OUTCOME_VOTING_PROXY, 0, removePayload, bytes32(0), removeSalt);

        console.log("");
        console.log("=== STAGE 1 SCHEDULED: removeValidator ===");
        console.log("Operation ID:");
        console.logBytes32(removeOpId);
        console.log("Executable after timestamp:", block.timestamp + delay);
        console.log("");
        console.log("Payload:");
        console.logBytes(removePayload);
        console.log("Salt:");
        console.logBytes32(removeSalt);
        console.log("");
        console.log("After ~72s, execute via:");
        console.log("  cast send", TIMELOCK);
        console.log("  'execute(address,uint256,bytes,bytes32,bytes32)'");
        console.log("  ", OUTCOME_VOTING_PROXY, "0 <removePayload> 0x0 <removeSalt>");
        console.log("");
        console.log("Then re-run this script with the same SIGNER to schedule");
        console.log("the addValidator stage (separate salt so no collision).");
    }
}
