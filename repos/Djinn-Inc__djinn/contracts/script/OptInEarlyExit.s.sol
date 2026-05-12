// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";

interface IOutcomeVoting {
    function requestEarlyExit(address genius, address idiot, uint256[] calldata purchaseIds) external;
    function earlyExitRequested(bytes32 batchKey) external view returns (bool);
}

interface IAccount {
    function getPairPurchaseIds(address genius, address idiot) external view returns (uint256[] memory);
}

/**
 * @title OptInEarlyExit
 * @notice For 9 stuck (G0, idiot) audit queues with sub-MIN_BATCH_SIZE
 *         purchases, call OV.requestEarlyExit as the genius. This sets
 *         earlyExitRequested[batchKey] = true so validators' submit gate
 *         (main.py:621) treats the batch as opted-in and proceeds with
 *         submitVote.
 *
 * Caller MUST be G0 (env: GENIUS_KEY).
 */
contract OptInEarlyExit is Script {
    address constant OV = 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5;
    address constant ACCOUNT = 0x4546354Dd32a613B76Abf530F81c8359e7cE440B;
    address constant G0 = 0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d;

    function run() external {
        address[9] memory idiots = [
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

        uint256 pk = vm.envUint("GENIUS_KEY");
        require(vm.addr(pk) == G0, "GENIUS_KEY does not derive G0");

        IOutcomeVoting ov = IOutcomeVoting(OV);
        IAccount acct = IAccount(ACCOUNT);

        vm.startBroadcast(pk);

        for (uint256 i = 0; i < 9; i++) {
            address idiot = idiots[i];
            uint256[] memory pids = acct.getPairPurchaseIds(G0, idiot);
            // Sort defensively (already ascending in observed data, but
            // requestEarlyExit reverts on non-strictly-ascending).
            for (uint256 j = 1; j < pids.length; j++) {
                require(pids[j] > pids[j - 1], "non-ascending");
            }
            console.log(string.concat("opt-in idiot ", vm.toString(idiot)), pids.length, "purchases");
            ov.requestEarlyExit(G0, idiot, pids);
        }

        vm.stopBroadcast();

        console.log("9 early-exit opt-ins submitted. Validators should re-vote on next epoch.");
    }
}
