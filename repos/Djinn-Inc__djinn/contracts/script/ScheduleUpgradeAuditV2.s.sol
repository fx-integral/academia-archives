// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Audit} from "../src/Audit.sol";

/// @title ScheduleUpgradeAuditV2
/// @notice Deploys a new Audit implementation (V2) and schedules the
///         pause → upgradeToAndCall(initializeV2) → unpause batch via the
///         TimelockController.
///
/// What this upgrade adds:
/// - `_settleCommon` now routes BOTH settle paths (regular + early-exit)
///   through `_distributeDamages`, so principal-USDC + excess-Credits is
///   the invariant rule on every entrypoint. Previously, early-exit gave
///   ALL damages in Credits even when the idiot paid in USDC.
/// - `autoEarlyExitDelay` state variable (default 45 days, settable via
///   `setAutoEarlyExitDelay` onlyOwner, bounded [1 day, 365 days]).
/// - On-chain precondition for `earlyExitByVote`: requires either
///   `OV.earlyExitRequested[batchKey] == true` (genius/idiot opted in)
///   OR `block.timestamp - max(p.purchasedAt) > autoEarlyExitDelay`
///   (SLA timeout fired). Otherwise reverts with `EarlyExitNotPermitted`.
///   This stops a colluding validator quorum from sneaking credits-only
///   settlement onto fresh pairs without consent.
/// - Both AuditSettled and EarlyExitSettled events fire on early-exit
///   (was: only EarlyExitSettled). Indexers see uniform tranche data.
///
/// Storage layout: autoEarlyExitDelay placed at slot 9 (was first slot
/// of __gap[41]); __gap reduced to [40]. Verified via `forge inspect`.
///
/// Why: see project memory feedback_settlement_consent_or_timeout.md
/// and feedback_credits_in_credits_out.md. The idiot must never extract
/// more USDC than they paid in (regulatory firewall: free speech with
/// SLA, not gambling). Every settlement path must obey this; previously
/// only the >=10-batch path did.
///
/// Usage:
///   forge script script/ScheduleUpgradeAuditV2.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL \
///     --broadcast
contract ScheduleUpgradeAuditV2 is Script {
    bytes32 constant SALT = keccak256("audit-v2-consent-or-timeout-2026-04-26");

    address constant AUDIT_PROXY = 0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Chain ID:", block.chainid);

        vm.startBroadcast(deployerKey);
        address auditImpl = address(new Audit());
        console.log("New Audit impl (V2):", auditImpl);

        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        // Step 1: pause Audit (required by _authorizeUpgrade modifier)
        targets[0] = AUDIT_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        // Step 2: upgrade impl + atomically call initializeV2() in same tx
        // initializeV2 sets autoEarlyExitDelay = DEFAULT_AUTO_EARLY_EXIT_DELAY
        // (45 days). msg.sender during the delegatecall is the timelock,
        // which is owner, so onlyOwner check passes.
        targets[1] = AUDIT_PROXY;
        payloads[1] =
            abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (auditImpl, abi.encodeWithSignature("initializeV2()")));

        // Step 3: unpause
        targets[2] = AUDIT_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

        uint256 delay = timelock.getMinDelay();
        timelock.scheduleBatch(targets, values, payloads, bytes32(0), SALT, delay);

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);
        vm.stopBroadcast();

        console.log("Audit V2 upgrade scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after (unix ts):", block.timestamp + delay);
        console.log("Delay (seconds):", delay);
        console.log("");
        console.log("Add to .env for ExecuteUpgradeAuditV2:");
        console.log("  AUDIT_IMPL_V2=", auditImpl);
    }
}
