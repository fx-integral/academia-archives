// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import {Audit} from "../src/Audit.sol";
import {OutcomeVoting} from "../src/OutcomeVoting.sol";

/// @title ExecuteUpgradeV7
/// @notice Executes the V7 Audit + OutcomeVoting upgrade after the timelock
///         delay has elapsed. Verifies ERC-1967 implementation slots match.
///
/// Required env vars (from ScheduleUpgradeV7 output):
///   AUDIT_IMPL_V7, OUTCOME_VOTING_IMPL_V7
///
/// Usage:
///   forge script script/ExecuteUpgradeV7.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast
contract ExecuteUpgradeV7 is Script {
    bytes32 constant UPGRADE_SALT = keccak256("v7-quorum-floor-onchain-notional");

    address constant AUDIT_PROXY = 0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E;
    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address auditImpl = vm.envAddress("AUDIT_IMPL_V7");
        address votingImpl = vm.envAddress("OUTCOME_VOTING_IMPL_V7");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Audit impl V7:", auditImpl);
        console.log("OutcomeVoting impl V7:", votingImpl);

        // Reconstruct the exact 6-op batch that was scheduled
        uint256 opCount = 6;
        address[] memory targets = new address[](opCount);
        uint256[] memory values = new uint256[](opCount);
        bytes[] memory payloads = new bytes[](opCount);

        targets[0] = AUDIT_PROXY;
        payloads[0] = abi.encodeCall(Audit.pause, ());

        targets[1] = OUTCOME_VOTING_PROXY;
        payloads[1] = abi.encodeCall(OutcomeVoting.pause, ());

        targets[2] = AUDIT_PROXY;
        payloads[2] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (auditImpl, ""));

        targets[3] = OUTCOME_VOTING_PROXY;
        payloads[3] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (votingImpl, ""));

        targets[4] = AUDIT_PROXY;
        payloads[4] = abi.encodeCall(Audit.unpause, ());

        targets[5] = OUTCOME_VOTING_PROXY;
        payloads[5] = abi.encodeCall(OutcomeVoting.unpause, ());

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), UPGRADE_SALT);
        console.log("Batch ID:");
        console.logBytes32(batchId);

        bool ready = timelock.isOperationReady(batchId);
        bool pending = timelock.isOperationPending(batchId);
        console.log("Operation pending:", pending);
        console.log("Operation ready:", ready);

        require(ready, "Not ready (delay not elapsed or not scheduled)");

        vm.startBroadcast(deployerKey);
        timelock.executeBatch(targets, values, payloads, bytes32(0), UPGRADE_SALT);
        vm.stopBroadcast();

        // Verify ERC-1967 implementation slots
        bytes32 implSlot = bytes32(uint256(keccak256("eip1967.proxy.implementation")) - 1);

        address[2] memory proxies = [AUDIT_PROXY, OUTCOME_VOTING_PROXY];
        address[2] memory expectedImpls = [auditImpl, votingImpl];
        string[2] memory names = ["Audit", "OutcomeVoting"];

        console.log("");
        console.log("=== POST-UPGRADE VERIFICATION ===");
        for (uint256 i = 0; i < 2; i++) {
            address actual = address(uint160(uint256(vm.load(proxies[i], implSlot))));
            console.log(names[i]);
            console.log("  Expected:", expectedImpls[i]);
            console.log("  Actual:", actual);
            console.log("  Match:", actual == expectedImpls[i]);
            require(actual == expectedImpls[i], "Implementation mismatch");
        }
        console.log("");
        console.log("V7 upgrade executed. Both proxies verified.");
    }
}
