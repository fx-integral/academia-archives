// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {Escrow} from "../src/Escrow.sol";
import {SignalCommitment} from "../src/SignalCommitment.sol";
import {Collateral} from "../src/Collateral.sol";
import {CreditLedger} from "../src/CreditLedger.sol";
// Aliased because forge-std exposes a built-in `Account` struct that
// would otherwise collide with the Djinn Account contract symbol.
import {Account as DjinnAccount} from "../src/Account.sol";
import {MockUSDC} from "./MockUSDC.sol";

/// @title EscrowV2.t.sol
/// @notice Tests for the Phase 2 additive Escrow upgrades:
///         - supportsFeature() capability discovery
///         - depositWithPermit() (skipped here; MockERC20 doesn't implement permit)
///         - purchaseV2() with Merkle root commitments
///         The legacy purchase() and deposit() paths are tested in
///         the existing Escrow.t.sol; this file only covers the new
///         additive surface to confirm strict additivity.
contract EscrowV2Test is Test {
    Escrow public escrow;
    SignalCommitment public signalCommitment;
    Collateral public collateral;
    CreditLedger public creditLedger;
    DjinnAccount public account;
    MockUSDC public usdc;

    address public owner = address(this);
    address public genius = address(0xBEEF);
    address public idiot = address(0xCAFE);

    function setUp() public {
        usdc = new MockUSDC();

        Escrow escrowImpl = new Escrow();
        ERC1967Proxy escrowProxy =
            new ERC1967Proxy(address(escrowImpl), abi.encodeCall(Escrow.initialize, (address(usdc), owner)));
        escrow = Escrow(address(escrowProxy));

        SignalCommitment scImpl = new SignalCommitment();
        ERC1967Proxy scProxy = new ERC1967Proxy(address(scImpl), abi.encodeCall(SignalCommitment.initialize, (owner)));
        signalCommitment = SignalCommitment(address(scProxy));

        Collateral collImpl = new Collateral();
        ERC1967Proxy collProxy =
            new ERC1967Proxy(address(collImpl), abi.encodeCall(Collateral.initialize, (address(usdc), owner)));
        collateral = Collateral(address(collProxy));

        CreditLedger clImpl = new CreditLedger();
        ERC1967Proxy clProxy = new ERC1967Proxy(address(clImpl), abi.encodeCall(CreditLedger.initialize, (owner)));
        creditLedger = CreditLedger(address(clProxy));

        DjinnAccount acctImpl = new DjinnAccount();
        ERC1967Proxy acctProxy = new ERC1967Proxy(address(acctImpl), abi.encodeCall(DjinnAccount.initialize, (owner)));
        account = DjinnAccount(address(acctProxy));

        escrow.setSignalCommitment(address(signalCommitment));
        escrow.setCollateral(address(collateral));
        escrow.setCreditLedger(address(creditLedger));
        escrow.setAccount(address(account));

        collateral.setAuthorized(address(escrow), true);
        creditLedger.setAuthorizedCaller(address(escrow), true);
        account.setAuthorizedCaller(address(escrow), true);
        signalCommitment.setAuthorizedCaller(address(escrow), true);
    }

    // -------------------------------------------------------------
    // supportsFeature
    // -------------------------------------------------------------

    function test_supportsFeature_purchaseV2() public view {
        assertTrue(escrow.supportsFeature(escrow.FEATURE_PURCHASE_V2()));
    }

    function test_supportsFeature_depositWithPermit() public view {
        assertTrue(escrow.supportsFeature(escrow.FEATURE_DEPOSIT_WITH_PERMIT()));
    }

    function test_supportsFeature_purchaseVectorMerkle() public view {
        assertTrue(escrow.supportsFeature(escrow.FEATURE_PURCHASE_VECTOR_MERKLE()));
    }

    function test_supportsFeature_unknown_returns_false() public view {
        assertFalse(escrow.supportsFeature(keccak256("RANDOM_FEATURE_THAT_DOES_NOT_EXIST")));
        assertFalse(escrow.supportsFeature(bytes32(0)));
    }

    // -------------------------------------------------------------
    // purchaseV2: zero-root rejection
    // -------------------------------------------------------------

    function test_purchaseV2_rejects_zero_bpa_root() public {
        bytes32 bpaRoot = bytes32(0);
        bytes32 wpaRoot = keccak256("nonzero");
        vm.expectRevert();
        escrow.purchaseV2(1, 1_000_000, 1_910_000, bpaRoot, wpaRoot);
    }

    function test_purchaseV2_rejects_zero_wpa_root() public {
        bytes32 bpaRoot = keccak256("nonzero");
        bytes32 wpaRoot = bytes32(0);
        vm.expectRevert();
        escrow.purchaseV2(1, 1_000_000, 1_910_000, bpaRoot, wpaRoot);
    }

    function test_purchaseV2_rejects_both_zero_roots() public {
        vm.expectRevert();
        escrow.purchaseV2(1, 1_000_000, 1_910_000, bytes32(0), bytes32(0));
    }

    // -------------------------------------------------------------
    // depositWithPermit: not testable here (MockERC20 has no permit)
    // -------------------------------------------------------------

    function test_depositWithPermit_reverts_on_non_permit_token() public {
        vm.prank(idiot);
        vm.expectRevert("permit_unsupported_or_invalid");
        escrow.depositWithPermit(1_000_000, block.timestamp + 1 hours, 27, bytes32(0), bytes32(0));
    }

    // -------------------------------------------------------------
    // Backwards compatibility: legacy purchase still works
    // -------------------------------------------------------------

    function test_legacy_deposit_still_works() public {
        usdc.mint(idiot, 10_000_000);
        vm.prank(idiot);
        usdc.approve(address(escrow), 10_000_000);
        vm.prank(idiot);
        escrow.deposit(10_000_000);
        assertEq(escrow.getBalance(idiot), 10_000_000);
    }

    function test_purchaseVectorRoots_zero_for_legacy_purchases() public view {
        // No purchase has been made, but querying purchaseId=0 should
        // return zero roots since this contract was deployed fresh.
        assertEq(escrow.purchaseBpaRoot(0), bytes32(0));
        assertEq(escrow.purchaseWpaRoot(0), bytes32(0));
    }
}
