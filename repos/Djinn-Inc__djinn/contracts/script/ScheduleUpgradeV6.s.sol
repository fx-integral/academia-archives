// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Escrow} from "../src/Escrow.sol";

/// @title ScheduleUpgradeV6
/// @notice Deploys a new Escrow implementation and schedules the
///         pause -> upgrade -> unpause batch via the TimelockController.
///
///         V6 adds to Escrow:
///           - purchaseV2(signalId, notional, odds, bpaRoot, wpaRoot)
///           - depositWithPermit(amount, deadline, v, r, s)
///           - supportsFeature(bytes32) for runtime capability discovery
///           - purchaseBpaRoot / purchaseWpaRoot Merkle root mappings
///           - PurchaseVectorRootsCommitted event
///
///         No other contracts changed since V5. Only Escrow is upgraded.
///         If V5 is still pending (not yet executed), this script cancels
///         it first since the new Escrow implementation already includes
///         the V5 fee fix in its compiled bytecode.
///
/// Usage:
///   forge script script/ScheduleUpgradeV6.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC \
///     --broadcast \
///     --verify
contract ScheduleUpgradeV6 is Script {
    bytes32 constant V5_SALT = keccak256("combined-v5-with-fee-fix");
    bytes32 constant V6_SALT = keccak256("escrow-v6-purchaseV2-permit");

    address constant ESCROW_PROXY = 0xb43BA175a6784973eB3825acF801Cd7920ac692a;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    // V5 proxy + impl sets (needed to reconstruct V5 batch for cancellation)
    address constant ACCOUNT_PROXY = 0x4546354Dd32a613B76Abf530F81c8359e7cE440B;
    address constant AUDIT_PROXY = 0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E;
    address constant OUTCOME_VOTING_PROXY = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant SIGNAL_COMMITMENT_PROXY = 0x4712479Ba57c9ED40405607b2B18967B359209C0;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Chain ID:", block.chainid);

        // ── Step 1: Cancel V5 if still pending ──────────────────────
        // V5 was a 15-operation batch (all 5 proxies). If it's still
        // pending, cancel it. The new Escrow impl compiled from the
        // current source already contains the V5 fee fix, so nothing
        // is lost.
        _cancelV5IfPending(timelock, deployerKey);

        // ── Step 2: Deploy new Escrow implementation ────────────────
        vm.startBroadcast(deployerKey);
        address escrowImpl = address(new Escrow());
        console.log("New Escrow impl:", escrowImpl);

        // ── Step 3: Schedule V6 (Escrow-only, 3 operations) ────────
        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        // Op 0: pause Escrow
        targets[0] = ESCROW_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        // Op 1: upgrade Escrow to new implementation
        targets[1] = ESCROW_PROXY;
        payloads[1] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (escrowImpl, ""));

        // Op 2: unpause Escrow
        targets[2] = ESCROW_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

        uint256 delay = timelock.getMinDelay();
        timelock.scheduleBatch(targets, values, payloads, bytes32(0), V6_SALT, delay);

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), V6_SALT);
        vm.stopBroadcast();

        console.log("V6 scheduled. Batch ID:");
        console.logBytes32(batchId);
        console.log("Executable after:", block.timestamp + delay);
        console.log("Delay (seconds):", delay);

        // Save the impl address for the execute script
        console.log("");
        console.log("Add to .env for ExecuteUpgradeV6:");
        console.log("  ESCROW_IMPL_V6=", escrowImpl);
    }

    /// @dev Reconstructs the V5 15-op batch and cancels it if pending.
    ///      Needs the V5 impl addresses from env (set them if V5 exists).
    function _cancelV5IfPending(TimelockController timelock, uint256 deployerKey) internal {
        // Try to read V5 impl addresses. If not set, V5 was probably
        // already executed or never scheduled, so skip silently.
        try vm.envAddress("ACCOUNT_IMPL_V5") returns (address accountV5) {
            address[5] memory v5Impls = [
                accountV5,
                vm.envAddress("ESCROW_IMPL_V5"),
                vm.envAddress("AUDIT_IMPL_V5"),
                vm.envAddress("OUTCOME_VOTING_IMPL_V5"),
                vm.envAddress("SIGNAL_IMPL_V5")
            ];
            address[5] memory proxies =
                [ACCOUNT_PROXY, ESCROW_PROXY, AUDIT_PROXY, OUTCOME_VOTING_PROXY, SIGNAL_COMMITMENT_PROXY];

            address[] memory t = new address[](15);
            uint256[] memory v = new uint256[](15);
            bytes[] memory p = new bytes[](15);
            for (uint256 i; i < 5; ++i) {
                t[i] = proxies[i];
                p[i] = abi.encodeWithSignature("pause()");
                t[i + 5] = proxies[i];
                p[i + 5] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (v5Impls[i], ""));
                t[i + 10] = proxies[i];
                p[i + 10] = abi.encodeWithSignature("unpause()");
            }

            bytes32 v5Id = timelock.hashOperationBatch(t, v, p, bytes32(0), V5_SALT);
            if (timelock.isOperationPending(v5Id)) {
                vm.startBroadcast(deployerKey);
                timelock.cancel(v5Id);
                vm.stopBroadcast();
                console.log("V5 batch CANCELLED (was pending)");
            } else {
                console.log("V5 not pending, skip cancel");
            }
        } catch {
            console.log("V5 impl addresses not in env, skip cancel check");
        }
    }
}
