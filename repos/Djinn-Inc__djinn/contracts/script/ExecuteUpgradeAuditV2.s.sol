// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/// @title ExecuteUpgradeAuditV2
/// @notice Executes the Audit V2 upgrade batch after the timelock delay
///         has elapsed. Pairs with ScheduleUpgradeAuditV2.
///
/// Usage:
///   export AUDIT_IMPL_V2=<impl address from schedule script>
///   forge script script/ExecuteUpgradeAuditV2.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC_URL \
///     --broadcast
contract ExecuteUpgradeAuditV2 is Script {
    bytes32 constant SALT = keccak256("audit-v2-consent-or-timeout-2026-04-26");

    address constant AUDIT_PROXY = 0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E;
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;

    function run() external {
        uint256 executorKey = vm.envUint("DEPLOYER_KEY");
        address auditImpl = vm.envAddress("AUDIT_IMPL_V2");
        TimelockController timelock = TimelockController(payable(TIMELOCK));

        console.log("Executor:", vm.addr(executorKey));
        console.log("Chain ID:", block.chainid);
        console.log("Audit impl V2:", auditImpl);

        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        targets[0] = AUDIT_PROXY;
        payloads[0] = abi.encodeWithSignature("pause()");

        targets[1] = AUDIT_PROXY;
        payloads[1] =
            abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (auditImpl, abi.encodeWithSignature("initializeV2()")));

        targets[2] = AUDIT_PROXY;
        payloads[2] = abi.encodeWithSignature("unpause()");

        bytes32 batchId = timelock.hashOperationBatch(targets, values, payloads, bytes32(0), SALT);
        require(timelock.isOperationReady(batchId), "Batch not ready (delay not elapsed or not scheduled)");

        vm.startBroadcast(executorKey);
        timelock.executeBatch(targets, values, payloads, bytes32(0), SALT);
        vm.stopBroadcast();

        console.log("Audit V2 upgrade executed. Batch ID:");
        console.logBytes32(batchId);
    }
}
