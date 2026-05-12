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
 * @title ForceSettleNew
 * @notice Owner-only emergency force-settle for one (genius, idiot) batch
 *         identified at runtime via env vars. Used to confirm the chain
 *         pipeline fires AuditSettled after share recovery shipped, even
 *         while outcome-resolution divergence prevents natural quorum.
 *
 *         qualityScore=0 (neutral) — no economic edge claimed by the
 *         "vote", just exercising the AuditSettled event path.
 *
 * Two-phase via env: PHASE=schedule then PHASE=execute (after 72s testnet delay).
 *
 * Required env: DEPLOYER_KEY, GENIUS, IDIOT
 * Optional env: QUALITY_SCORE (default 0), SALT_TAG (default unique-per-pair)
 */
contract ForceSettleNew is Script {
    address constant TIMELOCK = 0x37f41EFfa8492022afF48B9Ef725008963F14f79;
    address constant AUDIT = 0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E;
    address constant ACCOUNT = 0x4546354Dd32a613B76Abf530F81c8359e7cE440B;

    function run() external {
        address genius = vm.envAddress("GENIUS");
        address idiot = vm.envAddress("IDIOT");
        int256 qualityScore = int256(vm.envOr("QUALITY_SCORE", uint256(0)));
        string memory phase = vm.envOr("PHASE", string("schedule"));
        string memory saltTag = vm.envOr("SALT_TAG", string("force-settle-new"));

        bytes32 salt = keccak256(abi.encode(saltTag, genius, idiot));

        IAccount acct = IAccount(ACCOUNT);
        uint256[] memory pids = acct.getPairPurchaseIds(genius, idiot);
        require(pids.length > 0, "no purchases for pair");

        address[] memory targets = new address[](1);
        uint256[] memory values = new uint256[](1);
        bytes[] memory payloads = new bytes[](1);
        targets[0] = AUDIT;
        values[0] = 0;
        payloads[0] = abi.encodeWithSelector(IAudit.forceSettle.selector, genius, idiot, pids, qualityScore);

        console.log("phase:", phase);
        console.log("genius:", genius);
        console.log("idiot:", idiot);
        console.log("purchase_id count:", pids.length);
        console.log("qualityScore:", qualityScore);

        ITimelockController tlc = ITimelockController(TIMELOCK);
        uint256 pk = vm.envUint("DEPLOYER_KEY");
        vm.startBroadcast(pk);

        if (keccak256(bytes(phase)) == keccak256("schedule")) {
            uint256 delay = tlc.getMinDelay();
            console.log("delay (s):", delay);
            tlc.scheduleBatch(targets, values, payloads, bytes32(0), salt, delay);
            console.log("scheduled.");
        } else if (keccak256(bytes(phase)) == keccak256("execute")) {
            tlc.executeBatch(targets, values, payloads, bytes32(0), salt);
            console.log("executed.");
        } else {
            revert("PHASE must be 'schedule' or 'execute'");
        }
        vm.stopBroadcast();
    }
}
