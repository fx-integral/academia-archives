// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {LineOutcomeRegistry} from "../src/LineOutcomeRegistry.sol";

interface ITimelockController {
    function scheduleBatch(
        address[] calldata targets,
        uint256[] calldata values,
        bytes[] calldata payloads,
        bytes32 predecessor,
        bytes32 salt,
        uint256 delay
    ) external;

    function executeBatch(
        address[] calldata targets,
        uint256[] calldata values,
        bytes[] calldata payloads,
        bytes32 predecessor,
        bytes32 salt
    ) external payable;

    function getMinDelay() external view returns (uint256);
}

/// @title UpgradeLineOutcomeRegistry
/// @notice Two-step upgrade ceremony for LineOutcomeRegistry, batched into a
///         single TimelockController operation. The contract requires
///         `_authorizeUpgrade` to run while paused, so we batch:
///           1. pause()
///           2. upgradeToAndCall(newImpl, "")
///           3. unpause()
///         All three execute atomically once the timelock delay passes.
///
/// PHASE=schedule first, wait for delay (72s testnet, 72h mainnet), then
/// PHASE=execute. SALT_TAG defaults to "lor-upgrade-{block.timestamp}" so each
/// run gets a unique operation id.
///
/// Required env:
///   DEPLOYER_KEY            — timelock proposer/executor key
///   TIMELOCK_ADDRESS        — TimelockController
///   REGISTRY_PROXY_ADDRESS  — the LineOutcomeRegistry proxy
///   NEW_IMPL_ADDRESS        — the freshly-deployed new implementation
///   PHASE                   — "schedule" | "execute"
///   SALT_TAG                — optional, default "lor-upgrade-{ts}"
///
/// Usage:
///   PHASE=schedule forge script script/UpgradeLineOutcomeRegistry.s.sol --rpc-url ... --broadcast
///   # wait for timelock min delay
///   PHASE=execute forge script script/UpgradeLineOutcomeRegistry.s.sol --rpc-url ... --broadcast
contract UpgradeLineOutcomeRegistry is Script {
    function run() external {
        uint256 pk = vm.envUint("DEPLOYER_KEY");
        address timelock = vm.envAddress("TIMELOCK_ADDRESS");
        address proxy = vm.envAddress("REGISTRY_PROXY_ADDRESS");
        address newImpl = vm.envAddress("NEW_IMPL_ADDRESS");
        string memory phase = vm.envOr("PHASE", string("schedule"));
        string memory saltTag = vm.envOr(
            "SALT_TAG",
            string.concat("lor-upgrade-", vm.toString(block.timestamp))
        );

        require(timelock != address(0), "TIMELOCK_ADDRESS required");
        require(proxy != address(0), "REGISTRY_PROXY_ADDRESS required");
        require(newImpl != address(0), "NEW_IMPL_ADDRESS required");

        bytes32 salt = keccak256(abi.encode(saltTag, proxy, newImpl));

        // Build the three-call batch: pause -> upgrade -> unpause.
        address[] memory targets = new address[](3);
        uint256[] memory values = new uint256[](3);
        bytes[] memory payloads = new bytes[](3);

        targets[0] = proxy;
        targets[1] = proxy;
        targets[2] = proxy;
        // values[*] are 0 by default

        payloads[0] = abi.encodeCall(LineOutcomeRegistry.pause, ());
        payloads[1] = abi.encodeWithSelector(
            bytes4(keccak256("upgradeToAndCall(address,bytes)")),
            newImpl,
            bytes("")
        );
        payloads[2] = abi.encodeCall(LineOutcomeRegistry.unpause, ());

        ITimelockController tlc = ITimelockController(timelock);

        console.log("Chain ID:    ", block.chainid);
        console.log("Phase:       ", phase);
        console.log("Proxy:       ", proxy);
        console.log("New impl:    ", newImpl);
        console.log("Timelock:    ", timelock);
        console.log("Salt tag:    ", saltTag);

        vm.startBroadcast(pk);

        if (keccak256(bytes(phase)) == keccak256("schedule")) {
            uint256 delay = tlc.getMinDelay();
            console.log("Min delay:   ", delay, "seconds");
            tlc.scheduleBatch(targets, values, payloads, bytes32(0), salt, delay);
            console.log("");
            console.log("SCHEDULED. Wait for", delay, "seconds, then run with PHASE=execute SALT_TAG=", saltTag);
        } else if (keccak256(bytes(phase)) == keccak256("execute")) {
            tlc.executeBatch(targets, values, payloads, bytes32(0), salt);
            console.log("");
            console.log("EXECUTED. Verify proxy implementation:");
            console.log("  cast call <proxy> 'implementation()(address)' should return:", newImpl);
        } else {
            revert("PHASE must be 'schedule' or 'execute'");
        }

        vm.stopBroadcast();
    }
}
