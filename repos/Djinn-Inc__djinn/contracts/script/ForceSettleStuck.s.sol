// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";

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

interface IAudit {
    function forceSettle(address genius, address idiot, uint256[] calldata purchaseIds, int256 qualityScore) external;
}

interface IAccount {
    function getPairPurchaseIds(address genius, address idiot) external view returns (uint256[] memory);
}

/**
 * @title ForceSettleStuck
 * @notice Owner-only emergency settlement for the 3 stuck batches that
 *         couldn't reach the 4-of-5 quorum (validator_sync re-added UID 213
 *         after my removeValidator):
 *           idiot 0x6EC6a10b (1 voter missing share) — score 1531000
 *           idiot 0x2CaFE574 (1 voter missing share) — score -15000000
 *           idiot 0x7663f147 (2 voters missing shares) — score -15000000
 *
 *         All 3 batches' existing voters agree on these scores. forceSettle
 *         bypasses OV and directly invokes _settleCommon with the consensus
 *         score; totalNotional is recomputed on-chain from purchases.
 *
 * Two-phase via env: PHASE=schedule (default) calls scheduleBatch; PHASE=execute
 * calls executeBatch. Same SALT between phases.
 */
contract ForceSettleStuck is Script {
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;
    address constant AUDIT = 0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E;
    address constant ACCOUNT = 0x4546354Dd32a613B76Abf530F81c8359e7cE440B;
    address constant G0 = 0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d;

    bytes32 constant SALT = keccak256("djinn-p001-forcesettle-2026-04-30-v1");

    struct Stuck {
        address idiot;
        int256 qualityScore;
    }

    function _stuck() internal pure returns (Stuck[3] memory) {
        return [
            Stuck(0x6EC6a10bB5B131Ee22578a9889BD5f222b56dE9B, 1_531_000),
            Stuck(0x2CaFE574b0F11699B1D0AfF1abEb2830AAD97f41, -15_000_000),
            Stuck(0x7663f1471b10A9b9cAAdb6fe099d88C9871c2D6D, -15_000_000)
        ];
    }

    function _build()
        internal
        view
        returns (address[] memory targets, uint256[] memory values, bytes[] memory payloads)
    {
        Stuck[3] memory stuck = _stuck();
        IAccount acct = IAccount(ACCOUNT);
        targets = new address[](stuck.length);
        values = new uint256[](stuck.length);
        payloads = new bytes[](stuck.length);
        for (uint256 i = 0; i < stuck.length; i++) {
            targets[i] = AUDIT;
            values[i] = 0;
            uint256[] memory pids = acct.getPairPurchaseIds(G0, stuck[i].idiot);
            payloads[i] =
                abi.encodeWithSelector(IAudit.forceSettle.selector, G0, stuck[i].idiot, pids, stuck[i].qualityScore);
        }
    }

    function run() external {
        string memory phase = vm.envOr("PHASE", string("schedule"));
        ITimelockController tlc = ITimelockController(TIMELOCK);
        (address[] memory targets, uint256[] memory values, bytes[] memory payloads) = _build();
        console.log("Phase:", phase);
        console.log("Action count:", targets.length);

        uint256 pk = vm.envUint("DEPLOYER_KEY");
        vm.startBroadcast(pk);

        if (keccak256(bytes(phase)) == keccak256("schedule")) {
            uint256 delay = tlc.getMinDelay();
            console.log("scheduling with delay:", delay);
            tlc.scheduleBatch(targets, values, payloads, bytes32(0), SALT, delay);
            console.log("scheduled.");
        } else if (keccak256(bytes(phase)) == keccak256("execute")) {
            console.log("executing batch...");
            tlc.executeBatch(targets, values, payloads, bytes32(0), SALT);
            console.log("executed.");
        } else {
            revert("PHASE must be 'schedule' or 'execute'");
        }
        vm.stopBroadcast();
    }
}
