// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {LineOutcomeRegistry} from "../src/LineOutcomeRegistry.sol";

/// @title DeployLineOutcomeRegistry
/// @notice Standalone deployment for v1747's LineOutcomeRegistry. Additive
///         to the existing Djinn deployment; does NOT redeploy other contracts.
///
/// Deploys: LineOutcomeRegistry implementation + ERC1967Proxy.
/// Initializes the proxy atomically (deployer cannot be front-run on init
/// because we use the constructor's init-data path).
/// Initial owner = TimelockController (so all admin actions go through timelock
/// from day one — no transferOwnership step needed, no transient
/// deployer-as-owner window).
///
/// Required env:
///   DEPLOYER_KEY           — broadcaster's private key
///   TIMELOCK_ADDRESS       — Djinn TimelockController (mainnet/sepolia constant)
///   OUTCOME_VOTING_ADDRESS — existing OutcomeVoting proxy (validatorRegistry source)
///
/// Usage:
///   forge script script/DeployLineOutcomeRegistry.s.sol \
///     --rpc-url $BASE_RPC_URL \
///     --broadcast --verify
contract DeployLineOutcomeRegistry is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address timelock = vm.envAddress("TIMELOCK_ADDRESS");
        address outcomeVoting = vm.envAddress("OUTCOME_VOTING_ADDRESS");

        require(timelock != address(0), "TIMELOCK_ADDRESS required");
        require(outcomeVoting != address(0), "OUTCOME_VOTING_ADDRESS required");

        console.log("Chain ID:        ", block.chainid);
        console.log("Deployer:        ", vm.addr(deployerKey));
        console.log("Timelock (owner):", timelock);
        console.log("OutcomeVoting:   ", outcomeVoting);

        vm.startBroadcast(deployerKey);

        // 1. Deploy implementation.
        LineOutcomeRegistry impl = new LineOutcomeRegistry();
        console.log("Implementation:  ", address(impl));

        // 2. Deploy proxy + atomically initialize with timelock as owner.
        bytes memory initData = abi.encodeCall(
            LineOutcomeRegistry.initialize,
            (timelock, outcomeVoting)
        );
        ERC1967Proxy proxy = new ERC1967Proxy(address(impl), initData);
        console.log("Proxy (registry):", address(proxy));

        vm.stopBroadcast();

        // 3. Verify wiring.
        LineOutcomeRegistry registry = LineOutcomeRegistry(address(proxy));
        require(registry.owner() == timelock, "owner mismatch");
        require(address(registry.validatorRegistry()) == outcomeVoting, "validatorRegistry mismatch");
        require(registry.THRESHOLD() == 4, "threshold mismatch");
        require(
            registry.OUTCOME_RULESET_HASH() == keccak256("DJINN_OUTCOMES_V1"),
            "ruleset hash mismatch"
        );

        console.log("");
        console.log("=== LineOutcomeRegistry deployed ===");
        console.log("Proxy:           ", address(proxy));
        console.log("Implementation:  ", address(impl));
        console.log("Owner (timelock):", registry.owner());
        console.log("Validator src:   ", address(registry.validatorRegistry()));
        console.log("Threshold:       ", registry.THRESHOLD());
        console.log("Domain separator:");
        console.logBytes32(registry.domainSeparatorV4());
        console.log("");
        console.log("Next steps:");
        console.log("  1. Verify on Basescan (forge verify-contract).");
        console.log("  2. Update validator config: LINE_OUTCOME_REGISTRY=<proxy>.");
        console.log("  3. Update subgraph startBlock + address in subgraph.yaml.");
        console.log("  4. Run Phase 6 E2E with 1-2 fresh signals.");
    }
}
