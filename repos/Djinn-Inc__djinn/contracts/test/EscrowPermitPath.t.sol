// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {Escrow} from "../src/Escrow.sol";
import {MockUSDCPermit} from "./MockUSDCPermit.sol";

/// @title EscrowPermitPath.t.sol
/// @notice Exercises the depositWithPermit() happy path using a
///         permit-capable USDC fixture. EscrowV2.t.sol only covers the
///         revert path (because its MockUSDC lacks permit); this file
///         covers the code path that mainnet USDC will exercise.
contract EscrowPermitPathTest is Test {
    Escrow public escrow;
    MockUSDCPermit public usdc;

    // Fixed buyer whose private key we control, so we can generate
    // valid EIP-2612 permit signatures via vm.sign.
    uint256 constant BUYER_KEY = 0xBEEF;
    address public buyer;

    bytes32 constant PERMIT_TYPEHASH =
        keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)");

    function setUp() public {
        buyer = vm.addr(BUYER_KEY);
        usdc = new MockUSDCPermit();

        Escrow escrowImpl = new Escrow();
        ERC1967Proxy proxy =
            new ERC1967Proxy(address(escrowImpl), abi.encodeCall(Escrow.initialize, (address(usdc), address(this))));
        escrow = Escrow(address(proxy));

        usdc.mint(buyer, 100_000_000); // 100 USDC (6 decimals)
    }

    /// @dev Helper: build the EIP-712 digest for a permit and sign it.
    function _signPermit(
        address owner,
        address spender,
        uint256 value,
        uint256 nonce,
        uint256 deadline,
        uint256 signerKey
    ) internal view returns (uint8 v, bytes32 r, bytes32 s) {
        bytes32 structHash = keccak256(abi.encode(PERMIT_TYPEHASH, owner, spender, value, nonce, deadline));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", usdc.DOMAIN_SEPARATOR(), structHash));
        (v, r, s) = vm.sign(signerKey, digest);
    }

    function test_depositWithPermit_happyPath() public {
        uint256 amount = 10_000_000; // 10 USDC
        uint256 deadline = block.timestamp + 1 hours;
        uint256 nonce = usdc.nonces(buyer);

        (uint8 v, bytes32 r, bytes32 s) = _signPermit(buyer, address(escrow), amount, nonce, deadline, BUYER_KEY);

        uint256 balBefore = usdc.balanceOf(buyer);
        uint256 escrowBalBefore = usdc.balanceOf(address(escrow));

        vm.prank(buyer);
        escrow.depositWithPermit(amount, deadline, v, r, s);

        assertEq(usdc.balanceOf(buyer), balBefore - amount, "buyer drained");
        assertEq(usdc.balanceOf(address(escrow)), escrowBalBefore + amount, "escrow received");
        assertEq(escrow.balances(buyer), amount, "balance credited");
        // Permit consumed the nonce; signing with the same nonce again
        // must fail.
        assertEq(usdc.nonces(buyer), nonce + 1, "nonce advanced");
    }

    function test_depositWithPermit_rejectsReusedNonce() public {
        uint256 amount = 10_000_000;
        uint256 deadline = block.timestamp + 1 hours;
        uint256 nonce = usdc.nonces(buyer);

        (uint8 v, bytes32 r, bytes32 s) = _signPermit(buyer, address(escrow), amount, nonce, deadline, BUYER_KEY);

        vm.prank(buyer);
        escrow.depositWithPermit(amount, deadline, v, r, s);

        // Re-submitting the exact same permit must revert (nonce now N+1).
        vm.prank(buyer);
        vm.expectRevert();
        escrow.depositWithPermit(amount, deadline, v, r, s);
    }

    function test_depositWithPermit_rejectsExpiredDeadline() public {
        uint256 amount = 10_000_000;
        uint256 deadline = block.timestamp + 10 minutes;
        uint256 nonce = usdc.nonces(buyer);

        (uint8 v, bytes32 r, bytes32 s) = _signPermit(buyer, address(escrow), amount, nonce, deadline, BUYER_KEY);

        // Jump past the deadline.
        vm.warp(deadline + 1);
        vm.prank(buyer);
        vm.expectRevert();
        escrow.depositWithPermit(amount, deadline, v, r, s);
    }

    function test_depositWithPermit_rejectsWrongSigner() public {
        uint256 amount = 10_000_000;
        uint256 deadline = block.timestamp + 1 hours;
        uint256 nonce = usdc.nonces(buyer);

        // Sign with a different key (not the owner); permit() must
        // reject because ECRECOVER returns a different address.
        uint256 impostorKey = 0xBAD;
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(buyer, address(escrow), amount, nonce, deadline, impostorKey);

        vm.prank(buyer);
        vm.expectRevert();
        escrow.depositWithPermit(amount, deadline, v, r, s);
    }
}
