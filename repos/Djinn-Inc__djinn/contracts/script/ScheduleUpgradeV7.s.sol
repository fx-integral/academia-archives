// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import {Audit} from "../src/Audit.sol";
import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title ScheduleUpgradeV7
/// @notice Deploys new implementations for Audit and OutcomeVoting, then
///         schedules a 6-operation batch through the TimelockController:
///         pause, upgradeToAndCall, unpause for each of the 2 proxies.
///
///         V7 security fixes (codex-audit findings #28 + #29):
///           - Audit: use on-chain totalNotional for settlement math instead
///             of the validator-supplied value. Closes the attack vector where
///             a validator zeros totalNotional to eliminate protocol fees.
///           - OutcomeVoting: quorum floor guard — revert if totalValidators
///             drops below MIN_VALIDATORS at finalization time, even though
///             removeValidator already blocks below that threshold.
///
///         After the timelock delay, run ExecuteUpgradeV7.s.sol to execute.
///
/// Usage:
///   forge script script/ScheduleUpgradeV7.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
contract ScheduleUpgradeV7 is Script {
    bytes32 constant UPGRADE_SALT = keccak256("v7-quorum-floor-onchain-notional");

    address constant AUDIT_PROXY = 0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E;
    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address deployer = vm.addr(deployerKey);
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", deployer);
        console.log("Chain ID:", block.chainid);
        console.log("");

        vm.startBroadcast(deployerKey);

        // Deploy new implementation contracts
        address auditImpl = address(new Audit());
        address votingImpl = address(new OutcomeVoting());

        console.log("New implementations deployed:");
        console.log("  Audit impl:", auditImpl);
        console.log("  OutcomeVoting impl:", votingImpl);
        console.log("");

        // Build the 6-operation batch: (pause, upgrade, unpause) x 2 contracts
        uint256 opCount = 6;
        address[] memory targets = new address[](opCount);
        uint256[] memory values = new uint256[](opCount);
        bytes[] memory payloads = new bytes[](opCount);

        // Pause both proxies
        targets[0] = AUDIT_PROXY;
        payloads[0] = abi.encodeCall(Audit.pause, ());

        targets[1] = OUTCOME_VOTING_PROXY;
        payloads[1] = abi.encodeCall(OutcomeVoting.pause, ());

        // Upgrade both proxies
        targets[2] = AUDIT_PROXY;
        payloads[2] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (auditImpl, ""));

        targets[3] = OUTCOME_VOTING_PROXY;
        payloads[3] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (votingImpl, ""));

        // Unpause both proxies
        targets[4] = AUDIT_PROXY;
        payloads[4] = abi.encodeCall(Audit.unpause, ());

        targets[5] = OUTCOME_VOTING_PROXY;
        payloads[5] = abi.encodeCall(OutcomeVoting.unpause, ());

        // Schedule the batch through the timelock
        uint256 delay = timelock.getMinDelay();
        console.log("Timelock delay (seconds):", delay);

        timelock.scheduleBatch(targets, values, payloads, bytes32(0), UPGRADE_SALT, delay);

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), UPGRADE_SALT);

        vm.stopBroadcast();

        console.log("V7 batch scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after timestamp:", block.timestamp + delay);
        console.log("");

        console.log("");
        console.log("=== UPGRADE SCHEDULED (V7: Quorum Floor + On-chain Notional) ===");
        console.log("Proxy addresses (unchanged after upgrade):");
        console.log("  Audit:", AUDIT_PROXY);
        console.log("  OutcomeVoting:", OUTCOME_VOTING_PROXY);
        console.log("");
        console.log("Set these env vars for ExecuteUpgradeV7.s.sol:");
        console.log("  AUDIT_IMPL_V7=", auditImpl);
        console.log("  OUTCOME_VOTING_IMPL_V7=", votingImpl);
    }
}
