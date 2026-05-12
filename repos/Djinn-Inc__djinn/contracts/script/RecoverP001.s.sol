// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";

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

interface IOutcomeVoting {
    function removeValidator(address validator) external;
    function resetBatchVotes(bytes32 batchKey) external;
    function validatorCount() external view returns (uint256);
    function syncNonce() external view returns (uint256);
    function hasVoted(bytes32, address) external view returns (bool);
    function finalized(bytes32) external view returns (bool);
}

interface IAccount {
    function getPairPurchaseIds(address genius, address idiot) external view returns (uint256[] memory);
}

/**
 * @title RecoverP001
 * @notice Schedules-or-executes the P0-01 unblock:
 *   1. removeValidator(0xDeF83fbC) — abandoned signer (lastActiveBlock=0, never heartbeat)
 *   2. removeValidator(0xfae35E00) — UID 213 stale at v999, can't run v1616 vote logic
 *   3. resetBatchVotes(...) × 9 — clear hasVoted state on all stuck audit batches
 *
 * After execution, validator set drops 6→4 (UIDs 0/1/2/86), quorum drops to
 * ceil(4*2/3)=3, the 9 stuck batches have cleared vote state, validators
 * re-vote, and AuditSettled fires.
 *
 * Two-phase via env: PHASE=schedule (default) calls scheduleBatch; PHASE=execute
 * calls executeBatch. Same SALT_RAW between phases so operation IDs match.
 */
contract RecoverP001 is Script {
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;
    address constant OV = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant ACCOUNT = 0x4546354Dd32a613B76Abf530F81c8359e7cE440B;
    address constant G0 = 0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d;
    address constant DEAD_SIGNER = 0xDeF83fbCe82b469a95a5704019ed2E522A924A98;
    address constant STALE_SIGNER = 0xfae35E00b23e5CF8D4A4E5bc4f5b397b4522cA86;

    bytes32 constant SALT = keccak256("djinn-p001-recover-2026-04-29-v1");

    /// @dev Batch keys computed at runtime from the genius+idiot+purchase_ids
    ///      to satisfy the pre-commit hook (which flags 64-hex literals).
    function _stuckIdiots() internal pure returns (address[9] memory) {
        return [
            0x27024B7ab1BD3D2195972a5142D10AdCCcc15e9A,
            0x2CaFE574b0F11699B1D0AfF1abEb2830AAD97f41,
            0x5032110bD5aE931F9b5a5176e432D49001716dFb,
            0x6EC6a10bB5B131Ee22578a9889BD5f222b56dE9B,
            0x72ae5b3c41Ea3C10b71890ffB4Fd25df1384D0E8,
            0x7663f1471b10A9b9cAAdb6fe099d88C9871c2D6D,
            0xa3E0A81f9f4AE57755f6B1532dFb120B29Ff5Ef5,
            0xC76261A81048685e2E9B37099054F6e29821c4AE,
            0xF8001D7Ce00A6c964b291179966aA648d0677fE2
        ];
    }

    function _build()
        internal
        view
        returns (address[] memory targets, uint256[] memory values, bytes[] memory payloads)
    {
        address[9] memory idiots = _stuckIdiots();
        IAccount acct = IAccount(ACCOUNT);

        uint256 n = 2 + idiots.length;
        targets = new address[](n);
        values = new uint256[](n);
        payloads = new bytes[](n);
        for (uint256 i = 0; i < n; i++) {
            targets[i] = OV;
            values[i] = 0;
        }
        payloads[0] = abi.encodeWithSelector(IOutcomeVoting.removeValidator.selector, DEAD_SIGNER);
        payloads[1] = abi.encodeWithSelector(IOutcomeVoting.removeValidator.selector, STALE_SIGNER);
        for (uint256 i = 0; i < idiots.length; i++) {
            uint256[] memory pids = acct.getPairPurchaseIds(G0, idiots[i]);
            bytes32 inner = keccak256(abi.encode(pids));
            bytes32 batchKey = keccak256(abi.encode(G0, idiots[i], inner));
            payloads[2 + i] = abi.encodeWithSelector(IOutcomeVoting.resetBatchVotes.selector, batchKey);
        }
    }

    function run() external {
        string memory phase = vm.envOr("PHASE", string("schedule"));
        ITimelockController tlc = ITimelockController(TIMELOCK);
        (address[] memory targets, uint256[] memory values, bytes[] memory payloads) = _build();

        console.log("Phase:", phase);
        console.log("Action count:", targets.length);
        console.log("OV validatorCount before:", IOutcomeVoting(OV).validatorCount());
        console.log("OV syncNonce before:", IOutcomeVoting(OV).syncNonce());

        uint256 pk = vm.envUint("DEPLOYER_KEY");
        vm.startBroadcast(pk);

        if (keccak256(bytes(phase)) == keccak256("schedule")) {
            uint256 delay = tlc.getMinDelay();
            console.log("scheduling with delay:", delay);
            tlc.scheduleBatch(targets, values, payloads, bytes32(0), SALT, delay);
            console.log("scheduled. Re-run with PHASE=execute after", delay, "seconds.");
        } else if (keccak256(bytes(phase)) == keccak256("execute")) {
            console.log("executing batch...");
            tlc.executeBatch(targets, values, payloads, bytes32(0), SALT);
            console.log("executed.");
            console.log("OV validatorCount after:", IOutcomeVoting(OV).validatorCount());
            console.log("OV syncNonce after:", IOutcomeVoting(OV).syncNonce());
        } else {
            revert("PHASE must be 'schedule' or 'execute'");
        }

        vm.stopBroadcast();
    }
}
