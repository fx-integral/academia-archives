// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {MockUSDC} from "../MockUSDC.sol";
import {SignalCommitment} from "../../src/SignalCommitment.sol";
import {Escrow} from "../../src/Escrow.sol";
import {Collateral} from "../../src/Collateral.sol";
import {CreditLedger} from "../../src/CreditLedger.sol";
import {Account as DjinnAccount} from "../../src/Account.sol";
import {Audit, AuditResult} from "../../src/Audit.sol";
import {Outcome} from "../../src/interfaces/IDjinn.sol";
import {_deployProxy} from "../helpers/DeployHelpers.sol";

/// @title EmergencyRecoveryTest
/// @notice Drill tests for the emergency recovery runbook (P1-15).
///         Covers: forceSettle USDC economics, timelocked governance path,
///         emergency pause, and timelocked unpause.
///
/// Run: forge test --match-contract EmergencyRecovery -vv
contract EmergencyRecoveryTest is Test {
    MockUSDC usdc;
    SignalCommitment signalCommitment;
    Escrow escrow;
    Collateral collateral;
    CreditLedger creditLedger;
    DjinnAccount account;
    Audit audit;

    address owner;
    address pauser = address(0xAAAA);
    address genius = address(0xBEEF);
    address idiot = address(0xCAFE);
    address treasury = address(0xFEE5);

    uint256 constant MAX_PRICE_BPS = 500;
    uint256 constant SLA_MULTIPLIER_BPS = 15_000;
    uint256 constant NOTIONAL = 1000e6;
    uint256 constant ODDS = 1_910_000;
    uint256 constant TIMELOCK_DELAY = 259_200;

    uint256 nextSignalId = 1;

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

        escrow.setSignalCommitment(address(signalCommitment));
        escrow.setCollateral(address(collateral));
        escrow.setCreditLedger(address(creditLedger));
        escrow.setAccount(address(account));
        escrow.setAuditContract(address(audit));

        audit.setEscrow(address(escrow));
        audit.setCollateral(address(collateral));
        audit.setCreditLedger(address(creditLedger));
        audit.setAccount(address(account));
        audit.setSignalCommitment(address(signalCommitment));
        audit.setProtocolTreasury(treasury);

        signalCommitment.setAuthorizedCaller(address(escrow), true);
        collateral.setAuthorized(address(escrow), true);
        collateral.setAuthorized(address(audit), true);
        creditLedger.setAuthorizedCaller(address(escrow), true);
        creditLedger.setAuthorizedCaller(address(audit), true);
        account.setAuthorizedCaller(address(escrow), true);
        account.setAuthorizedCaller(address(audit), true);
        account.setAuthorizedCaller(owner, true);
        escrow.setAuthorizedCaller(owner, true);

        audit.setPauser(pauser);
        escrow.setPauser(pauser);
        collateral.setPauser(pauser);
        signalCommitment.setPauser(pauser);
        account.setPauser(pauser);
        creditLedger.setPauser(pauser);
    }

    // ─── Helpers
    // ──────────────────────────────────────────────────────────────

    function _createSignal() internal returns (uint256 signalId) {
        signalId = nextSignalId++;
        string[] memory decoys = new string[](10);
        for (uint256 i; i < 10; i++) {
            decoys[i] = "decoy";
        }
        string[] memory books = new string[](2);
        books[0] = "DraftKings";
        books[1] = "FanDuel";

        vm.prank(genius);
        signalCommitment.commit(
            SignalCommitment.CommitParams({
                signalId: signalId,
                encryptedBlob: hex"deadbeef",
                commitHash: keccak256(abi.encodePacked("signal", signalId)),
                sport: "NFL",
                maxPriceBps: MAX_PRICE_BPS,
                slaMultiplierBps: SLA_MULTIPLIER_BPS,
                maxNotional: 10_000e6,
                minNotional: 0,
                expiresAt: block.timestamp + 1 days,
                decoyLines: decoys,
                availableSportsbooks: books,
                linesHash: bytes32(0),
                lineCount: 0,
                bpaMode: false
            })
        );
    }

    function _purchaseSignal(uint256 signalId) internal returns (uint256 purchaseId) {
        uint256 slaLock = (NOTIONAL * SLA_MULTIPLIER_BPS) / 10_000;
        uint256 protocolLock = (NOTIONAL * 50) / 10_000;
        uint256 fee = (NOTIONAL * MAX_PRICE_BPS) / 10_000;

        usdc.mint(genius, slaLock + protocolLock + fee);
        vm.startPrank(genius);
        usdc.approve(address(collateral), slaLock + protocolLock + fee);
        collateral.deposit(slaLock + protocolLock + fee);
        vm.stopPrank();

        usdc.mint(idiot, fee);
        vm.startPrank(idiot);
        usdc.approve(address(escrow), fee);
        escrow.deposit(fee);
        purchaseId = escrow.purchase(signalId, NOTIONAL, ODDS);
        vm.stopPrank();
    }

    function _recordOutcome(uint256 purchaseId, Outcome outcome) internal {
        account.recordOutcome(genius, idiot, purchaseId, outcome);
        escrow.setOutcome(purchaseId, outcome);
    }

    function _buildBatch(uint256 count, Outcome outcome) internal returns (uint256[] memory purchaseIds) {
        purchaseIds = new uint256[](count);
        for (uint256 i; i < count; i++) {
            uint256 sigId = _createSignal();
            purchaseIds[i] = _purchaseSignal(sigId);
            _recordOutcome(purchaseIds[i], outcome);
        }
    }

    function _makeTimelock() internal returns (TimelockController timelock) {
        address[] memory proposers = new address[](1);
        proposers[0] = owner;
        address[] memory executors = new address[](1);
        executors[0] = address(0);
        timelock = new TimelockController(TIMELOCK_DELAY, proposers, executors, address(0));
    }

    // ─── Force-settle economic assertions
    // ────────────────────────────────────

    function test_forceSettle_positive_score_fees_claimable_by_genius() public {
        // Validator MPC failed on a batch. Owner provides an authoritative quality score.
        // Positive score: no damages; all fees belong to genius.
        uint256[] memory purchaseIds = _buildBatch(1, Outcome.Favorable);
        uint256 fee = (NOTIONAL * MAX_PRICE_BPS) / 10_000; // 50 USDC

        audit.forceSettle(genius, idiot, purchaseIds, 500e6);

        AuditResult memory r = audit.getAuditResult(genius, idiot, 0);
        assertEq(r.qualityScore, 500e6, "score recorded");
        assertEq(r.trancheA, 0, "no USDC damages");
        assertEq(r.trancheB, 0, "no credit damages");
        assertEq(escrow.batchClaimable(genius, idiot, 0), fee, "all fees claimable");
        assertGt(r.protocolFee, 0, "protocol fee slashed from collateral");
    }

    function test_forceSettle_small_batch_negative_score_principal_usdc_excess_credits() public {
        // V2 (2026-04-26): forceSettle on a small batch (< MIN_BATCH_SIZE)
        // takes the early-exit path internally, but damages currency is now
        // invariant across all settlement entrypoints: principal in USDC up to
        // sum(usdcPaid), excess in Credits. Pre-V2, this asserted "all credits".
        uint256[] memory purchaseIds = _buildBatch(1, Outcome.Unfavorable);
        int256 qualityScore = -500e6;

        uint256 idiotUsdcBefore = usdc.balanceOf(idiot);
        uint256 geniusCollateralBefore = collateral.deposits(genius);

        // Compute expected USDC cap from on-chain record.
        uint256 totalUsdcPaid = escrow.getPurchase(purchaseIds[0]).usdcPaid;
        uint256 damages = 500e6;
        uint256 expectedTrancheA = damages < totalUsdcPaid ? damages : totalUsdcPaid;
        uint256 expectedTrancheB = damages - expectedTrancheA;

        audit.forceSettle(genius, idiot, purchaseIds, qualityScore);

        AuditResult memory r = audit.getAuditResult(genius, idiot, 0);
        assertEq(r.trancheA, expectedTrancheA, "trancheA = min(damages, usdcPaid)");
        assertEq(r.trancheB, expectedTrancheB, "trancheB = excess damages");
        assertEq(creditLedger.balanceOf(idiot), expectedTrancheB, "idiot credits = trancheB");
        assertEq(usdc.balanceOf(idiot) - idiotUsdcBefore, expectedTrancheA, "idiot USDC = trancheA");
        // Genius collateral slashed by trancheA + protocolFee.
        assertEq(
            collateral.deposits(genius),
            geniusCollateralBefore - r.protocolFee - expectedTrancheA,
            "genius collateral slashed by trancheA + protocolFee"
        );
    }

    function test_forceSettle_full_batch_negative_score_slashes_usdc_to_idiot() public {
        // Full batch (>= MIN_BATCH_SIZE=10): trancheA slashes genius collateral → USDC to idiot.
        // Damages < fees paid → trancheA = damages, trancheB = 0.
        uint256[] memory purchaseIds = _buildBatch(10, Outcome.Unfavorable);

        // totalUsdcFeesPaid = 10 * 50e6 = 500e6
        // damages = 300e6 < 500e6 → trancheA = 300e6, trancheB = 0, netClaimable = 200e6
        int256 qualityScore = -300e6;
        uint256 expectedTrancheA = 300e6;
        uint256 expectedNetClaimable = 200e6;

        uint256 idiotUsdcBefore = usdc.balanceOf(idiot);
        audit.forceSettle(genius, idiot, purchaseIds, qualityScore);

        AuditResult memory r = audit.getAuditResult(genius, idiot, 0);
        assertEq(r.trancheA, expectedTrancheA, "trancheA: USDC slashed to idiot");
        assertEq(r.trancheB, 0, "no credit overflow");
        assertEq(usdc.balanceOf(idiot) - idiotUsdcBefore, expectedTrancheA, "idiot received USDC");
        assertEq(escrow.batchClaimable(genius, idiot, 0), expectedNetClaimable, "genius claimable = fees - trancheA");
    }

    function test_forceSettle_full_batch_damages_exceed_fees_overflow_to_credits() public {
        // Damages > fees paid → trancheA = all fees, trancheB = overflow as credits.
        uint256[] memory purchaseIds = _buildBatch(10, Outcome.Unfavorable);

        // totalUsdcFeesPaid = 500e6, damages = 800e6 → trancheA=500e6, trancheB=300e6
        int256 qualityScore = -800e6;
        uint256 expectedTrancheA = 500e6;
        uint256 expectedTrancheB = 300e6;

        audit.forceSettle(genius, idiot, purchaseIds, qualityScore);

        AuditResult memory r = audit.getAuditResult(genius, idiot, 0);
        assertEq(r.trancheA, expectedTrancheA, "trancheA capped at total fees paid");
        assertEq(r.trancheB, expectedTrancheB, "trancheB = overflow as credits");
        assertEq(creditLedger.balanceOf(idiot), expectedTrancheB, "idiot received credits for overflow");
        assertEq(escrow.batchClaimable(genius, idiot, 0), 0, "no fees remain for genius");
    }

    function test_forceSettle_genius_claims_fees_after_delay() public {
        // After forceSettle, genius must wait FEE_CLAIM_DELAY before claiming fees.
        uint256[] memory purchaseIds = _buildBatch(1, Outcome.Favorable);
        uint256 fee = (NOTIONAL * MAX_PRICE_BPS) / 10_000; // 50 USDC

        audit.forceSettle(genius, idiot, purchaseIds, 500e6);

        // Cannot claim immediately
        vm.prank(genius);
        vm.expectRevert();
        escrow.claimFees(idiot, 0);

        vm.warp(block.timestamp + escrow.FEE_CLAIM_DELAY() + 1);

        uint256 geniusUsdcBefore = usdc.balanceOf(genius);
        vm.prank(genius);
        escrow.claimFees(idiot, 0);
        assertEq(usdc.balanceOf(genius) - geniusUsdcBefore, fee, "genius received fees after delay");
        assertEq(escrow.batchClaimable(genius, idiot, 0), 0, "claimable zeroed after claim");
    }

    // ─── Governance path: timelocked forceSettle
    // ─────────────────────────────

    function test_timelocked_forceSettle_full_governance_path() public {
        // Proves the real production recovery sequence operators would use.
        TimelockController timelock = _makeTimelock();
        audit.transferOwnership(address(timelock));

        uint256[] memory purchaseIds = _buildBatch(1, Outcome.Favorable);
        int256 qualityScore = 100e6;

        bytes memory callData = abi.encodeCall(audit.forceSettle, (genius, idiot, purchaseIds, qualityScore));
        timelock.schedule(address(audit), 0, callData, bytes32(0), bytes32(0), TIMELOCK_DELAY);

        // Blocked before delay expires
        vm.expectRevert();
        timelock.execute(address(audit), 0, callData, bytes32(0), bytes32(0));

        vm.warp(block.timestamp + TIMELOCK_DELAY + 1);
        timelock.execute(address(audit), 0, callData, bytes32(0), bytes32(0));

        AuditResult memory r = audit.getAuditResult(genius, idiot, 0);
        assertEq(r.qualityScore, qualityScore, "settlement executed via timelock");
        assertGt(r.timestamp, 0, "settlement recorded");
    }

    function test_timelocked_forceSettle_cannot_be_replayed() public {
        // A timelock operation can only be executed once (nonce exhausted after execute).
        TimelockController timelock = _makeTimelock();
        audit.transferOwnership(address(timelock));

        uint256[] memory purchaseIds = _buildBatch(1, Outcome.Favorable);
        bytes memory callData = abi.encodeCall(audit.forceSettle, (genius, idiot, purchaseIds, 100e6));
        bytes32 opId = timelock.hashOperation(address(audit), 0, callData, bytes32(0), bytes32(0));

        timelock.schedule(address(audit), 0, callData, bytes32(0), bytes32(0), TIMELOCK_DELAY);
        vm.warp(block.timestamp + TIMELOCK_DELAY + 1);
        timelock.execute(address(audit), 0, callData, bytes32(0), bytes32(0));

        // Operation is consumed; a second execute attempt reverts
        vm.expectRevert();
        timelock.execute(address(audit), 0, callData, bytes32(0), bytes32(0));

        assertFalse(timelock.isOperationPending(opId), "operation consumed after execution");
    }

    // ─── Emergency pause mechanics
    // ────────────────────────────────────────────

    function test_emergency_pause_blocks_purchases_and_withdrawals() public {
        // A single pauser call freezes all user-facing escrow operations.
        uint256 signalId = _createSignal();
        uint256 fee = (NOTIONAL * MAX_PRICE_BPS) / 10_000;
        uint256 slaLock = (NOTIONAL * SLA_MULTIPLIER_BPS) / 10_000;
        uint256 protocolLock = (NOTIONAL * 50) / 10_000;

        usdc.mint(genius, slaLock + protocolLock + fee);
        vm.startPrank(genius);
        usdc.approve(address(collateral), slaLock + protocolLock + fee);
        collateral.deposit(slaLock + protocolLock + fee);
        vm.stopPrank();

        usdc.mint(idiot, fee);
        vm.startPrank(idiot);
        usdc.approve(address(escrow), fee);
        escrow.deposit(fee);
        vm.stopPrank();

        vm.prank(pauser);
        escrow.pause();
        assertTrue(escrow.paused());

        vm.prank(idiot);
        vm.expectRevert();
        escrow.purchase(signalId, NOTIONAL, ODDS);

        vm.prank(idiot);
        vm.expectRevert();
        escrow.withdraw(1);
    }

    function test_emergency_pause_blocks_audit_settlement() public {
        uint256[] memory purchaseIds = _buildBatch(1, Outcome.Favorable);

        vm.prank(pauser);
        audit.pause();

        vm.expectRevert();
        audit.forceSettle(genius, idiot, purchaseIds, 100e6);
    }

    function test_timelocked_unpause_restores_all_operations() public {
        // Full freeze → governance unpause → operations resume.
        TimelockController timelock = _makeTimelock();
        audit.transferOwnership(address(timelock));
        escrow.transferOwnership(address(timelock));

        vm.prank(pauser);
        escrow.pause();
        assertTrue(escrow.paused());

        bytes memory unpauseData = abi.encodeCall(Escrow.unpause, ());
        timelock.schedule(address(escrow), 0, unpauseData, bytes32(0), bytes32(0), TIMELOCK_DELAY);

        // Still blocked before delay
        vm.expectRevert();
        timelock.execute(address(escrow), 0, unpauseData, bytes32(0), bytes32(0));

        vm.warp(block.timestamp + TIMELOCK_DELAY + 1);
        timelock.execute(address(escrow), 0, unpauseData, bytes32(0), bytes32(0));
        assertFalse(escrow.paused(), "escrow unpaused after timelock");

        // Operations resume
        usdc.mint(idiot, 100e6);
        vm.startPrank(idiot);
        usdc.approve(address(escrow), 100e6);
        escrow.deposit(100e6);
        vm.stopPrank();
        assertEq(escrow.balances(idiot), 100e6, "deposits work after unpause");
    }

    function test_pauser_cannot_unpause_only_owner_can() public {
        // Pauser has fire-only authority; unpause requires owner (or timelock) sign-off.
        vm.prank(pauser);
        audit.pause();

        vm.prank(pauser);
        vm.expectRevert();
        audit.unpause();

        // Owner can unpause directly (when owner hasn't transferred to timelock)
        audit.unpause();
        assertFalse(audit.paused());
    }

    function test_parallel_unpause_within_single_timelock_window() public {
        // Runbook recommendation: schedule both escrow and audit unpauses in one batch
        // so the freeze window stays at TIMELOCK_DELAY, not 2x.
        TimelockController timelock = _makeTimelock();
        audit.transferOwnership(address(timelock));
        escrow.transferOwnership(address(timelock));

        vm.startPrank(pauser);
        audit.pause();
        escrow.pause();
        vm.stopPrank();

        bytes memory unpauseAudit = abi.encodeCall(Audit.unpause, ());
        bytes memory unpauseEscrow = abi.encodeCall(Escrow.unpause, ());

        // Schedule both in the same block (different salts to avoid nonce collision)
        timelock.schedule(address(audit), 0, unpauseAudit, bytes32(0), bytes32("audit"), TIMELOCK_DELAY);
        timelock.schedule(address(escrow), 0, unpauseEscrow, bytes32(0), bytes32("escrow"), TIMELOCK_DELAY);

        vm.warp(block.timestamp + TIMELOCK_DELAY + 1);

        timelock.execute(address(audit), 0, unpauseAudit, bytes32(0), bytes32("audit"));
        timelock.execute(address(escrow), 0, unpauseEscrow, bytes32(0), bytes32("escrow"));

        assertFalse(audit.paused(), "audit unpaused");
        assertFalse(escrow.paused(), "escrow unpaused");
    }
}
