// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Escrow} from "../src/Escrow.sol";

/// @title ExecuteUpgradeV6
/// @notice Executes the V6 Escrow upgrade after the timelock delay has elapsed.
///         Verifies the ERC-1967 implementation slot matches the expected address.
///
/// Usage:
///   forge script script/ExecuteUpgradeV6.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC \
///     --broadcast
///
/// Requires .env:
///   DEPLOYER_KEY=...
///   ESCROW_IMPL_V6=<address from ScheduleUpgradeV6 output>
contract ExecuteUpgradeV6 is Script {
    bytes32 constant UPGRADE_SALT = keccak256("escrow-v6-purchaseV2-permit");

    address constant ESCROW_PROXY = 0xb43BA175a6784973eB3825acF801Cd7920ac692a;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address escrowImpl = vm.envAddress("ESCROW_IMPL_V6");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Deployer:", vm.addr(deployerKey));
        console.log("Escrow impl V6:", escrowImpl);

        // Build the same 3-operation batch that was scheduled
        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        targets[0] = ESCROW_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        targets[1] = ESCROW_PROXY;
        payloads[1] = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (escrowImpl, ""));

        targets[2] = ESCROW_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

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

        // Verify the ERC-1967 implementation slot was updated
        bytes32 implSlot = bytes32(uint256(keccak256("eip1967.proxy.implementation")) - 1);
        address actual = address(uint160(uint256(vm.load(ESCROW_PROXY, implSlot))));
        require(actual == escrowImpl, "Implementation mismatch after upgrade");

        console.log("V6 upgrade executed successfully.");
        console.log("Escrow proxy now points to:", actual);

        // Verify new features are accessible
        Escrow escrow = Escrow(ESCROW_PROXY);
        bool hasPV2 = escrow.supportsFeature(keccak256("PURCHASE_V2"));
        bool hasPermit = escrow.supportsFeature(keccak256("DEPOSIT_WITH_PERMIT"));
        bool hasMerkle = escrow.supportsFeature(keccak256("PURCHASE_VECTOR_MERKLE"));
        console.log("supportsFeature(PURCHASE_V2):", hasPV2);
        console.log("supportsFeature(DEPOSIT_WITH_PERMIT):", hasPermit);
        console.log("supportsFeature(PURCHASE_VECTOR_MERKLE):", hasMerkle);

        require(hasPV2, "PURCHASE_V2 feature not detected");
        require(hasPermit, "DEPOSIT_WITH_PERMIT feature not detected");
        require(hasMerkle, "PURCHASE_VECTOR_MERKLE feature not detected");
    }
}
