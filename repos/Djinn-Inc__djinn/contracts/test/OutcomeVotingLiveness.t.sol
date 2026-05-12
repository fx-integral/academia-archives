// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "./MockUSDC.sol";
import {SignalCommitment} from "../src/SignalCommitment.sol";
import {Escrow} from "../src/Escrow.sol";
import {Collateral} from "../src/Collateral.sol";
import {CreditLedger} from "../src/CreditLedger.sol";
import {Account as DjinnAccount} from "../src/Account.sol";
import {Audit} from "../src/Audit.sol";
import {OutcomeVoting} from "../src/OutcomeVoting.sol";
import {_deployProxy} from "./helpers/DeployHelpers.sol";

/// @title OutcomeVotingLivenessTest
/// @notice Tests for P0-11 liveness-aware quorum. Validates that the quorum
///         denominator auto-shrinks around offline signers and auto-recovers
///         when they come back, without any admin intervention.
contract OutcomeVotingLivenessTest is Test {
    MockUSDC usdc;
    SignalCommitment signalCommitment;
    Escrow escrow;
    Collateral collateral;
    CreditLedger creditLedger;
    DjinnAccount account;
    Audit audit;
    OutcomeVoting voting;

    address owner;
    address treasury = address(0xFEE5);
    address genius = address(0xBEEF);
    address idiot = address(0xCAFE);

    address v1 = address(0xA001);
    address v2 = address(0xA002);
    address v3 = address(0xA003);
    address v4 = address(0xA004);
    address v5 = address(0xA005);
    address v6 = address(0xA006);

    uint256 constant WINDOW = 1800; // ~1h on Base
    uint256 constant NOTIONAL = 1000e6;

    function setUp() public {
        owner = address(this);
        usdc = new MockUSDC();
        signalCommitment = SignalCommitment(
            _deployProxy(address(new SignalCommitment()), abi.encodeCall(SignalCommitment.initialize, (owner)))
        );
        escrow = Escrow(_deployProxy(address(new Escrow()), abi.encodeCall(Escrow.initialize, (address(usdc), owner))));
        collateral = Collateral(
            _deployProxy(address(new Collateral()), abi.encodeCall(Collateral.initialize, (address(usdc), owner)))
        );
        creditLedger =
            CreditLedger(_deployProxy(address(new CreditLedger()), abi.encodeCall(CreditLedger.initialize, (owner))));
        account =
            DjinnAccount(_deployProxy(address(new DjinnAccount()), abi.encodeCall(DjinnAccount.initialize, (owner))));
        audit = Audit(_deployProxy(address(new Audit()), abi.encodeCall(Audit.initialize, (owner))));
        voting = OutcomeVoting(
            _deployProxy(address(new OutcomeVoting()), abi.encodeCall(OutcomeVoting.initialize, (owner)))
        );
        audit.setEscrow(address(escrow));
        audit.setCollateral(address(collateral));
        audit.setCreditLedger(address(creditLedger));
        audit.setAccount(address(account));
        audit.setSignalCommitment(address(signalCommitment));
        audit.setProtocolTreasury(treasury);
        audit.setOutcomeVoting(address(voting));
        voting.setAudit(address(audit));
        voting.setAccount(address(account));

        voting.addValidator(v1);
        voting.addValidator(v2);
        voting.addValidator(v3);
        voting.addValidator(v4);
        voting.addValidator(v5);
        voting.addValidator(v6);

        // Roll to a nonzero block so activeWindow arithmetic has room.
        vm.roll(10_000);
    }

    // ─── Config + Events
    // ─────────────────────────────────────────────────

    function test_activeWindow_default_zero() public view {
        assertEq(voting.activeWindow(), 0, "default must be 0 (legacy)");
    }

    function test_setActiveWindow_onlyOwner() public {
        vm.prank(v1);
        vm.expectRevert();
        voting.setActiveWindow(WINDOW);
    }

    function test_setActiveWindow_updates_and_emits() public {
        vm.expectEmit(true, true, true, true);
        emit OutcomeVoting.ActiveWindowUpdated(0, WINDOW);
        voting.setActiveWindow(WINDOW);
        assertEq(voting.activeWindow(), WINDOW);
    }

    // ─── Legacy behavior preserved
    // ───────────────────────────────────────

    function test_livenessOff_activeCount_equals_validators_length() public view {
        assertEq(voting.activeWindow(), 0);
        assertEq(voting.activeCount(), 6);
    }

    function test_livenessOff_isActive_true_for_all_validators() public view {
        assertTrue(voting.isActive(v1));
        assertTrue(voting.isActive(v2));
        assertTrue(voting.isActive(v6));
    }

    function test_livenessOff_isActive_false_for_non_validators() public view {
        assertFalse(voting.isActive(address(0xDEAD)));
    }

    function test_livenessOff_quorumThreshold_unchanged() public view {
        // 6 validators, 2/3 → ceil(12/3) = 4
        assertEq(voting.quorumThreshold(), 4);
    }

    // ─── Liveness-aware quorum
    // ────────────────────────────────────────────

    function test_livenessOn_activeCount_zero_before_any_activity() public {
        voting.setActiveWindow(WINDOW);
        // No validator has ever voted or heartbeated; all have
        // lastActiveBlock=0, which is < cutoff. So activeCount=0.
        assertEq(voting.activeCount(), 0);
    }

    function test_livenessOn_activeCount_reflects_heartbeats() public {
        voting.setActiveWindow(WINDOW);
        vm.prank(v1);
        voting.heartbeat();
        vm.prank(v2);
        voting.heartbeat();
        vm.prank(v3);
        voting.heartbeat();
        assertEq(voting.activeCount(), 3);
    }

    function test_livenessOn_active_status_decays_after_window() public {
        voting.setActiveWindow(WINDOW);
        vm.prank(v1);
        voting.heartbeat();
        assertTrue(voting.isActive(v1));
        assertEq(voting.activeCount(), 1);

        // Still active at window edge
        vm.roll(block.number + WINDOW);
        assertTrue(voting.isActive(v1));
        assertEq(voting.activeCount(), 1);

        // Inactive one block past window
        vm.roll(block.number + 1);
        assertFalse(voting.isActive(v1));
        assertEq(voting.activeCount(), 0);
    }

    function test_livenessOn_heartbeat_refreshes_active_status() public {
        voting.setActiveWindow(WINDOW);
        vm.prank(v1);
        voting.heartbeat();

        vm.roll(block.number + WINDOW + 100); // now stale
        assertFalse(voting.isActive(v1));

        vm.prank(v1);
        voting.heartbeat();
        assertTrue(voting.isActive(v1));
    }

    function test_livenessOn_heartbeat_reverts_non_validator() public {
        voting.setActiveWindow(WINDOW);
        vm.prank(address(0xDEAD));
        vm.expectRevert(abi.encodeWithSelector(OutcomeVoting.NotValidator.selector, address(0xDEAD)));
        voting.heartbeat();
    }

    function test_livenessOn_heartbeat_ticks_lastActiveBlock() public {
        voting.setActiveWindow(WINDOW);
        assertEq(voting.lastActiveBlock(v1), 0);

        vm.roll(12_345);
        vm.prank(v1);
        voting.heartbeat();
        assertEq(voting.lastActiveBlock(v1), 12_345);
    }

    // ─── Quorum denominator dynamics
    // ────────────────────────────────────

    function test_livenessOn_quorum_shrinks_as_validators_go_offline() public {
        voting.setActiveWindow(WINDOW);

        // All 6 active → quorum = ceil(6*2/3) = 4
        _heartbeatAll();
        assertEq(voting.quorumThreshold(), 4);
        assertEq(voting.activeCount(), 6);

        // 1 offline (5 active) → quorum = ceil(5*2/3) = 4 (still)
        vm.roll(block.number + WINDOW / 2);
        vm.prank(v1);
        voting.heartbeat();
        vm.prank(v2);
        voting.heartbeat();
        vm.prank(v3);
        voting.heartbeat();
        vm.prank(v4);
        voting.heartbeat();
        vm.prank(v5);
        voting.heartbeat();
        // v6 did not heartbeat; will go stale after remaining window

        vm.roll(block.number + WINDOW / 2 + 1); // v6 now stale, v1-v5 within window
        assertEq(voting.activeCount(), 5);
        assertEq(voting.quorumThreshold(), 4);

        // Two more offline: 3 active → quorum = ceil(3*2/3) = 2
        vm.roll(block.number + WINDOW / 4);
        vm.prank(v1);
        voting.heartbeat();
        vm.prank(v2);
        voting.heartbeat();
        vm.prank(v3);
        voting.heartbeat();
        vm.roll(block.number + WINDOW / 2);
        // Only v1/v2/v3 heartbeated within window; v4/v5 went stale; v6 was already stale
        assertEq(voting.activeCount(), 3);
        assertEq(voting.quorumThreshold(), 2);
    }

    function test_livenessOn_min_validators_floor_applies() public {
        voting.setActiveWindow(WINDOW);
        // Only 1 validator active; denominator must floor at MIN_VALIDATORS=3
        vm.prank(v1);
        voting.heartbeat();
        assertEq(voting.activeCount(), 1);
        // quorumThreshold uses validators.length (external view), which is 6.
        // The internal _quorumDenominator (used on submitVote) applies the floor.
        // Since first-vote snapshot uses _quorumDenominator(), the floor is
        // enforced at vote-snapshot time. We can validate indirectly: the
        // snapshot after first vote must be max(activeCount, MIN_VALIDATORS) = 3.
        // See test_livenessOn_firstVote_snapshots_floored_activeCount below.
    }

    // ─── Quorum snapshot at first vote
    // ───────────────────────────────────

    function test_livenessOn_firstVote_snapshots_activeCount_not_total() public {
        voting.setActiveWindow(WINDOW);
        // 3 validators active at first-vote moment
        vm.prank(v1);
        voting.heartbeat();
        vm.prank(v2);
        voting.heartbeat();
        vm.prank(v3);
        voting.heartbeat();

        bytes32 bk = _voteOn(v1, 100, NOTIONAL, false);
        // Snapshot must be 3 (active) not 6 (total)
        assertEq(voting.cycleValidatorSnapshot(bk), 3, "snapshot must equal active count at first vote");
    }

    function test_livenessOn_firstVote_snapshots_floored_activeCount() public {
        voting.setActiveWindow(WINDOW);
        // Only 1 validator active. MIN_VALIDATORS=3 floor must kick in.
        vm.prank(v1);
        voting.heartbeat();

        bytes32 bk = _voteOn(v1, 100, NOTIONAL, false);
        // Active count was 1 (v1 only, via heartbeat; v1's submitVote also
        // ticks their timestamp but we checked activeCount BEFORE vote).
        // Snapshot should be max(1, MIN_VALIDATORS=3) = 3.
        // But v1 is the one voting, and their submitVote ticks them active,
        // so activeCount at call time is 1. Floor → 3.
        assertEq(voting.cycleValidatorSnapshot(bk), 3);
    }

    function test_livenessOn_subsequent_activity_does_not_change_snapshot() public {
        voting.setActiveWindow(WINDOW);
        vm.prank(v1);
        voting.heartbeat();
        vm.prank(v2);
        voting.heartbeat();
        vm.prank(v3);
        voting.heartbeat();

        bytes32 bk = _voteOn(v1, 100, NOTIONAL, false);
        assertEq(voting.cycleValidatorSnapshot(bk), 3);

        // v4/v5/v6 heartbeat AFTER first vote. Snapshot must not change.
        vm.prank(v4);
        voting.heartbeat();
        vm.prank(v5);
        voting.heartbeat();
        vm.prank(v6);
        voting.heartbeat();

        assertEq(voting.cycleValidatorSnapshot(bk), 3, "snapshot locks at first-vote moment");
    }

    function test_livenessOn_submitVote_ticks_lastActiveBlock() public {
        voting.setActiveWindow(WINDOW);
        vm.prank(v1);
        voting.heartbeat();
        vm.prank(v2);
        voting.heartbeat();
        vm.prank(v3);
        voting.heartbeat();

        vm.roll(block.number + 500);
        assertEq(voting.lastActiveBlock(v1), 10_000);

        _voteOn(v1, 100, NOTIONAL, false);

        assertEq(voting.lastActiveBlock(v1), block.number, "submitVote must tick liveness");
    }

    // ─── Kooltek-like scenario: self-healing through outage + recovery ──

    function test_livenessOn_offline_validator_self_heals_via_shrunken_quorum() public {
        // Initial: 6 validators, all active, quorum=4
        voting.setActiveWindow(WINDOW);
        _heartbeatAll();
        assertEq(voting.activeCount(), 6);
        assertEq(voting.quorumThreshold(), 4);

        // v6 (think: Kooltek) goes offline — stops heartbeating
        // Everyone else keeps voting/heartbeating within the window
        vm.roll(block.number + WINDOW / 2);
        _heartbeatExcept(v6);

        vm.roll(block.number + WINDOW / 2 + 1);
        // v6 is now stale; 5 active
        assertEq(voting.activeCount(), 5);
        // Quorum among 5 active = ceil(5*2/3) = 4 (same). So this outage alone
        // doesn't change the threshold; next outage does.

        // Now v5 also goes offline
        vm.roll(block.number + WINDOW / 2);
        vm.prank(v1);
        voting.heartbeat();
        vm.prank(v2);
        voting.heartbeat();
        vm.prank(v3);
        voting.heartbeat();
        vm.prank(v4);
        voting.heartbeat();

        vm.roll(block.number + WINDOW / 2 + 1);
        // v5, v6 stale; 4 active → quorum = ceil(4*2/3) = 3
        assertEq(voting.activeCount(), 4);
        assertEq(voting.quorumThreshold(), 3);

        // v6 (Kooltek) comes back tomorrow
        vm.roll(block.number + 1000);
        vm.prank(v6);
        voting.heartbeat();
        // Now v1/v2/v3/v4/v6 should be active (assuming v5 still stale)
        // But v1-v4 were heartbeated 1000+ blocks ago; if that's still within
        // window they're active. Let's check activeCount.
        // Actually the previous heartbeats were at block N; we advanced N+1
        // (for v5/v6 to go stale), then advanced 1000. So v1-v4 timestamps
        // are N+WINDOW/2, we're now at N+WINDOW/2+1+1000. So v1-v4 last
        // activity was 1001 blocks ago; still within window if WINDOW>=1001.
        assertTrue(voting.isActive(v6), "v6 came back online");
    }

    // ─── Helpers
    // ─────────────────────────────────────────────────────────

    function _heartbeatAll() internal {
        vm.prank(v1);
        voting.heartbeat();
        vm.prank(v2);
        voting.heartbeat();
        vm.prank(v3);
        voting.heartbeat();
        vm.prank(v4);
        voting.heartbeat();
        vm.prank(v5);
        voting.heartbeat();
        vm.prank(v6);
        voting.heartbeat();
    }

    function _heartbeatExcept(address skip) internal {
        if (v1 != skip) {
            vm.prank(v1);
            voting.heartbeat();
        }
        if (v2 != skip) {
            vm.prank(v2);
            voting.heartbeat();
        }
        if (v3 != skip) {
            vm.prank(v3);
            voting.heartbeat();
        }
        if (v4 != skip) {
            vm.prank(v4);
            voting.heartbeat();
        }
        if (v5 != skip) {
            vm.prank(v5);
            voting.heartbeat();
        }
        if (v6 != skip) {
            vm.prank(v6);
            voting.heartbeat();
        }
    }

    /// @dev Cast a vote with a single purchaseId so the test doesn't need
    ///      real purchase state. The Audit.settleByVote call will revert
    ///      if quorum is reached and no purchases exist on-chain, so we
    ///      keep these tests at sub-quorum vote counts.
    function _voteOn(address voter, int256 score, uint256 notional, bool isEarlyExit) internal returns (bytes32) {
        uint256[] memory ids = new uint256[](1);
        ids[0] = 1;
        vm.prank(voter);
        voting.submitVote(genius, idiot, ids, score, notional, isEarlyExit);
        return voting.computeBatchKey(genius, idiot, ids);
    }
}
