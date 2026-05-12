// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Test.sol";
import {KeyRecovery} from "../src/KeyRecovery.sol";
import {_deployProxy} from "./helpers/DeployHelpers.sol";

contract KeyRecoveryTest is Test {
    KeyRecovery public kr;

    address public owner = address(0xD00D);
    address public user1 = address(0xA1);
    address public user2 = address(0xA2);

    function setUp() public {
        kr = KeyRecovery(_deployProxy(address(new KeyRecovery()), abi.encodeCall(KeyRecovery.initialize, (owner))));
    }

    // ─── Tests: Store and retrieve recovery blob
    // ─────────────────────────

    function test_storeAndRetrieve() public {
        bytes memory blob = hex"deadbeefcafebabe";

        vm.prank(user1);
        kr.storeRecoveryBlob(blob);

        bytes memory retrieved = kr.getRecoveryBlob(user1);
        assertEq(keccak256(retrieved), keccak256(blob));
    }

    function test_storeRecoveryBlob_emitsEvent() public {
        bytes memory blob = hex"1234";

        vm.expectEmit(true, false, false, true);
        emit KeyRecovery.RecoveryBlobStored(user1, block.timestamp);

        vm.prank(user1);
        kr.storeRecoveryBlob(blob);
    }

    function test_getRecoveryBlob_emptyForUnset() public view {
        bytes memory retrieved = kr.getRecoveryBlob(user1);
        assertEq(retrieved.length, 0);
    }

    // ─── Tests: Overwrite existing blob
    // ──────────────────────────────────

    function test_overwriteExistingBlob() public {
        bytes memory blob1 = hex"aaaa";
        bytes memory blob2 = hex"bbbbbbbb";

        vm.prank(user1);
        kr.storeRecoveryBlob(blob1);

        vm.prank(user1);
        kr.storeRecoveryBlob(blob2);

        bytes memory retrieved = kr.getRecoveryBlob(user1);
        assertEq(keccak256(retrieved), keccak256(blob2));
        assertEq(retrieved.length, 4); // blob2 is 4 bytes
    }

    // ─── Tests: Different users have different blobs
    // ─────────────────────

    function test_differentUsersHaveDifferentBlobs() public {
        bytes memory blob1 = hex"1111";
        bytes memory blob2 = hex"2222";

        vm.prank(user1);
        kr.storeRecoveryBlob(blob1);

        vm.prank(user2);
        kr.storeRecoveryBlob(blob2);

        bytes memory retrieved1 = kr.getRecoveryBlob(user1);
        bytes memory retrieved2 = kr.getRecoveryBlob(user2);

        assertEq(keccak256(retrieved1), keccak256(blob1));
        assertEq(keccak256(retrieved2), keccak256(blob2));
        assertTrue(keccak256(retrieved1) != keccak256(retrieved2));
    }

    // ─── Tests: Revert on empty blob
    // ─────────────────────────────────────

    function test_storeRecoveryBlob_revertOnEmpty() public {
        vm.expectRevert(KeyRecovery.EmptyBlob.selector);
        vm.prank(user1);
        kr.storeRecoveryBlob("");
    }

    // ─── Tests: Large blob storage
    // ───────────────────────────────────────

    function test_storeLargeBlob() public {
        // 1024 bytes blob
        bytes memory largeBlob = new bytes(1024);
        for (uint256 i = 0; i < 1024; i++) {
            largeBlob[i] = bytes1(uint8(i % 256));
        }

        vm.prank(user1);
        kr.storeRecoveryBlob(largeBlob);

        bytes memory retrieved = kr.getRecoveryBlob(user1);
        assertEq(retrieved.length, 1024);
        assertEq(keccak256(retrieved), keccak256(largeBlob));
    }

    // ─── Tests: Blob size limits
    // ───────────────────────────────────────

    function test_storeBlobAtMaxSize() public {
        bytes memory blob = new bytes(kr.MAX_BLOB_SIZE());
        blob[0] = 0x01;
        vm.prank(user1);
        kr.storeRecoveryBlob(blob);
        assertEq(kr.getRecoveryBlob(user1).length, kr.MAX_BLOB_SIZE());
    }

    function test_storeBlobExceedsMaxSize() public {
        bytes memory blob = new bytes(kr.MAX_BLOB_SIZE() + 1);
        blob[0] = 0x01;
        vm.expectRevert(
            abi.encodeWithSelector(KeyRecovery.BlobTooLarge.selector, kr.MAX_BLOB_SIZE() + 1, kr.MAX_BLOB_SIZE())
        );
        vm.prank(user1);
        kr.storeRecoveryBlob(blob);
    }

    // ─── UUPS upgrade tests (P1-18)
    // ─────────────────────────────────────

    function test_uups_ownerCanUpgrade() public {
        address newImpl = address(new KeyRecovery());
        vm.prank(owner);
        (bool ok,) = address(kr).call(abi.encodeWithSignature("upgradeToAndCall(address,bytes)", newImpl, ""));
        assertTrue(ok, "owner upgrade should succeed");
    }

    function test_uups_nonOwnerCannotUpgrade() public {
        address newImpl = address(new KeyRecovery());
        vm.prank(user1);
        (bool ok,) = address(kr).call(abi.encodeWithSignature("upgradeToAndCall(address,bytes)", newImpl, ""));
        assertFalse(ok, "non-owner upgrade must revert");
    }

    function test_uups_blobsSurviveUpgrade() public {
        // Store a blob, upgrade impl, verify blob still retrievable.
        bytes memory blob = hex"deadbeefdeadbeef";
        vm.prank(user1);
        kr.storeRecoveryBlob(blob);

        address newImpl = address(new KeyRecovery());
        vm.prank(owner);
        (bool ok,) = address(kr).call(abi.encodeWithSignature("upgradeToAndCall(address,bytes)", newImpl, ""));
        assertTrue(ok, "upgrade should succeed");

        assertEq(keccak256(kr.getRecoveryBlob(user1)), keccak256(blob), "blob lost across upgrade");
    }

    function test_initialize_cannotBeCalledTwice() public {
        vm.expectRevert();
        kr.initialize(address(0xBEEF));
    }

    // ─── Pausable tests (P1-27)
    // ─────────────────────────────────────────

    address public pauser_ = address(0xBEEE);

    function test_pausable_defaultUnpaused() public view {
        assertFalse(kr.paused(), "fresh deploy should be unpaused");
    }

    function test_pausable_setPauser_onlyOwner() public {
        vm.prank(user1);
        vm.expectRevert();
        kr.setPauser(pauser_);

        vm.prank(owner);
        kr.setPauser(pauser_);
        assertEq(kr.pauser(), pauser_);
    }

    function test_pausable_pauseBlocksWrites() public {
        vm.prank(owner);
        kr.setPauser(pauser_);

        vm.prank(pauser_);
        kr.pause();
        assertTrue(kr.paused());

        bytes memory blob = hex"1234";
        vm.prank(user1);
        vm.expectRevert(); // PausableUpgradeable.EnforcedPause
        kr.storeRecoveryBlob(blob);
    }

    function test_pausable_pauseDoesNotBlockReads() public {
        // Pre-populate, then pause, then confirm read still works.
        bytes memory blob = hex"cafe";
        vm.prank(user1);
        kr.storeRecoveryBlob(blob);

        vm.prank(owner);
        kr.pause();

        // reads must stay open so users can always recover during a pause
        bytes memory retrieved = kr.getRecoveryBlob(user1);
        assertEq(keccak256(retrieved), keccak256(blob));
    }

    function test_pausable_unpauseRestoresWrites() public {
        vm.prank(owner);
        kr.pause();

        bytes memory blob = hex"dead";
        vm.prank(user1);
        vm.expectRevert();
        kr.storeRecoveryBlob(blob);

        vm.prank(owner);
        kr.unpause();

        vm.prank(user1);
        kr.storeRecoveryBlob(blob);
        assertEq(keccak256(kr.getRecoveryBlob(user1)), keccak256(blob));
    }

    function test_pausable_ownerCanPauseWithoutPauser() public {
        // Owner must always be able to pause even if pauser is unset.
        assertEq(kr.pauser(), address(0));

        vm.prank(owner);
        kr.pause();
        assertTrue(kr.paused());
    }

    function test_pausable_unpauseOnlyOwner() public {
        vm.prank(owner);
        kr.pause();

        vm.prank(pauser_);
        vm.expectRevert();
        kr.unpause();
        assertTrue(kr.paused(), "pauser must not be able to unpause");
    }

    function test_pausable_randomAddrCannotPause() public {
        vm.prank(user1);
        vm.expectRevert(abi.encodeWithSelector(KeyRecovery.NotPauserOrOwner.selector, user1));
        kr.pause();
    }

    function test_pausable_setPauserEmitsEvent() public {
        vm.expectEmit(true, false, false, false);
        emit KeyRecovery.PauserUpdated(pauser_);
        vm.prank(owner);
        kr.setPauser(pauser_);
    }

    // ─── P1-27 storage preservation across Pausable upgrade
    // ─────────────────────

    function test_p127_initializeV2_preservesExistingBlobs() public {
        // Simulate a pre-Pausable deployment: blob stored before upgrade must
        // remain readable after upgrade + initializeV2.
        bytes memory blob = hex"01020304050607";
        vm.prank(user1);
        kr.storeRecoveryBlob(blob);

        address newImpl = address(new KeyRecovery());
        vm.prank(owner);
        (bool ok,) = address(kr)
            .call(
                abi.encodeWithSignature(
                    "upgradeToAndCall(address,bytes)", newImpl, abi.encodeCall(KeyRecovery.initializeV2, ())
                )
            );
        assertTrue(ok, "upgrade + initializeV2 must succeed");

        // Blob survives (slot 0 untouched).
        assertEq(keccak256(kr.getRecoveryBlob(user1)), keccak256(blob), "blob lost across v2 init");
        // Pausable state initialized to false (ERC-7201 slot was zero).
        assertFalse(kr.paused(), "v2 init should leave paused=false");
    }

    function test_p127_initializeV2_notReentrant() public {
        vm.prank(owner);
        (bool okA,) = address(kr).call(abi.encodeCall(KeyRecovery.initializeV2, ()));
        assertTrue(okA, "first initializeV2 must succeed");

        vm.prank(owner);
        (bool okB,) = address(kr).call(abi.encodeCall(KeyRecovery.initializeV2, ()));
        assertFalse(okB, "second initializeV2 must revert (reinitializer(2) gate)");
    }

    function test_p127_initializeV2_onlyOwner() public {
        // Non-owner cannot burn the reinitializer(2) version by front-running the
        // timelock's upgradeToAndCall. Matters for the non-atomic upgradeTo + separate
        // initializeV2 path: without onlyOwner, any address could race the timelock.
        vm.prank(user1);
        (bool ok,) = address(kr).call(abi.encodeCall(KeyRecovery.initializeV2, ()));
        assertFalse(ok, "non-owner initializeV2 must revert");

        // Owner path still works; version gate still fires exactly once.
        vm.prank(owner);
        (bool ok2,) = address(kr).call(abi.encodeCall(KeyRecovery.initializeV2, ()));
        assertTrue(ok2, "owner initializeV2 must succeed after non-owner was blocked");
    }
}
