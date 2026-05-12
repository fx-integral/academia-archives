"""Tests for purchase orchestration."""

import pytest

from djinn_validator.core.mpc import MPCResult
from djinn_validator.core.purchase import PurchaseOrchestrator, PurchaseStatus
from djinn_validator.core.shares import ShareStore
from djinn_validator.utils.crypto import Share


class TestPurchaseOrchestrator:
    def setup_method(self) -> None:
        self.store = ShareStore()
        self.orch = PurchaseOrchestrator(self.store)

    def test_initiate_without_share_fails(self) -> None:
        req = self.orch.initiate("sig-1", "0xBuyer", "DraftKings")
        assert req.status == PurchaseStatus.FAILED

    def test_initiate_with_share(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req = self.orch.initiate("sig-1", "0xBuyer", "DraftKings")
        assert req.status == PurchaseStatus.CHECKING_AVAILABILITY

    def test_mpc_available(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        self.orch.initiate("sig-1", "0xBuyer", "DK")
        req = self.orch.set_mpc_result(
            "sig-1",
            "0xBuyer",
            MPCResult(available=True, participating_validators=7),
        )
        assert req is not None
        assert req.status == PurchaseStatus.AWAITING_PAYMENT

    def test_mpc_unavailable(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        self.orch.initiate("sig-1", "0xBuyer", "DK")
        req = self.orch.set_mpc_result(
            "sig-1",
            "0xBuyer",
            MPCResult(available=False, participating_validators=7),
        )
        assert req is not None
        assert req.status == PurchaseStatus.UNAVAILABLE

    def test_confirm_payment_releases_share(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"secret")
        self.orch.initiate("sig-1", "0xBuyer", "DK")
        self.orch.set_mpc_result(
            "sig-1",
            "0xBuyer",
            MPCResult(available=True, participating_validators=7),
        )
        req = self.orch.confirm_payment("sig-1", "0xBuyer", "0xTxHash")
        assert req is not None
        assert req.status == PurchaseStatus.SHARES_RELEASED
        assert req.tx_hash == "0xTxHash"

    def test_get_purchase(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        self.orch.initiate("sig-1", "0xBuyer", "DK")
        req = self.orch.get("sig-1", "0xBuyer")
        assert req is not None
        assert req.signal_id == "sig-1"

    def test_get_nonexistent(self) -> None:
        assert self.orch.get("none", "0x") is None

    def test_duplicate_initiate_returns_existing(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req1 = self.orch.initiate("sig-1", "0xBuyer", "DK")
        req2 = self.orch.initiate("sig-1", "0xBuyer", "FD")
        assert req1 is req2

    def test_cleanup_completed_removes_old_terminal(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req = self.orch.initiate("sig-1", "0xBuyer", "DK")
        # Set to terminal state with old timestamp
        req.status = PurchaseStatus.SHARES_RELEASED
        req.created_at = 0.0  # Very old

        removed = self.orch.cleanup_completed(max_age_seconds=1)
        assert removed == 1
        assert self.orch.get("sig-1", "0xBuyer") is None

    def test_cleanup_completed_keeps_recent(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req = self.orch.initiate("sig-1", "0xBuyer", "DK")
        req.status = PurchaseStatus.SHARES_RELEASED
        # created_at defaults to now — recent

        removed = self.orch.cleanup_completed(max_age_seconds=86400)
        assert removed == 0

    def test_cleanup_completed_keeps_active(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req = self.orch.initiate("sig-1", "0xBuyer", "DK")
        req.created_at = 0.0  # Very old but still active

        removed = self.orch.cleanup_completed(max_age_seconds=1)
        assert removed == 0  # Not terminal, should not be cleaned

    def test_double_confirm_payment_returns_early(self) -> None:
        """Second confirm_payment returns existing request without re-releasing."""
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"secret")
        self.orch.initiate("sig-1", "0xBuyer", "DK")
        self.orch.set_mpc_result(
            "sig-1",
            "0xBuyer",
            MPCResult(available=True, participating_validators=7),
        )
        req1 = self.orch.confirm_payment("sig-1", "0xBuyer", "0xTx1")
        assert req1 is not None
        assert req1.status == PurchaseStatus.SHARES_RELEASED

        # Second call should return early with same request
        req2 = self.orch.confirm_payment("sig-1", "0xBuyer", "0xTx2")
        assert req2 is not None
        assert req2.status == PurchaseStatus.SHARES_RELEASED
        # tx_hash should NOT be overwritten
        assert req2.tx_hash == "0xTx1"

    def test_confirm_after_confirmed_returns_early(self) -> None:
        """If status is PAYMENT_CONFIRMED (e.g. release failed), don't re-attempt."""
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"secret")
        self.orch.initiate("sig-1", "0xBuyer", "DK")
        self.orch.set_mpc_result(
            "sig-1",
            "0xBuyer",
            MPCResult(available=True, participating_validators=7),
        )
        # Manually set to PAYMENT_CONFIRMED as if release didn't happen yet
        req = self.orch.get("sig-1", "0xBuyer")
        assert req is not None
        req.status = PurchaseStatus.PAYMENT_CONFIRMED
        req.tx_hash = "0xOriginal"

        # Second confirm should return early
        req2 = self.orch.confirm_payment("sig-1", "0xBuyer", "0xNew")
        assert req2 is not None
        assert req2.tx_hash == "0xOriginal"

    def test_set_mpc_result_nonexistent(self) -> None:
        result = self.orch.set_mpc_result("nope", "0x", MPCResult(available=True, participating_validators=1))
        assert result is None

    def test_confirm_payment_nonexistent(self) -> None:
        result = self.orch.confirm_payment("nope", "0x", "0xTx")
        assert result is None


class TestStaleCleanup:
    """Purchases stuck in transient states should be failed after timeout."""

    def setup_method(self) -> None:
        self.store = ShareStore()
        self.orch = PurchaseOrchestrator(self.store)

    def test_stale_checking_availability_gets_failed(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req = self.orch.initiate("sig-1", "0xBuyer", "DK")
        assert req.status == PurchaseStatus.CHECKING_AVAILABILITY
        # Simulate being stuck for a long time
        req.created_at = 0.0
        failed = self.orch.cleanup_stale(stale_timeout=1)
        assert failed == 1
        assert req.status == PurchaseStatus.FAILED

    def test_stale_mpc_in_progress_gets_failed(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req = self.orch.initiate("sig-1", "0xBuyer", "DK")
        req.status = PurchaseStatus.MPC_IN_PROGRESS
        req.created_at = 0.0
        failed = self.orch.cleanup_stale(stale_timeout=1)
        assert failed == 1
        assert req.status == PurchaseStatus.FAILED

    def test_recent_transient_not_failed(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        self.orch.initiate("sig-1", "0xBuyer", "DK")
        # created_at defaults to now — not stale
        failed = self.orch.cleanup_stale(stale_timeout=300)
        assert failed == 0

    def test_terminal_state_not_touched(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req = self.orch.initiate("sig-1", "0xBuyer", "DK")
        req.status = PurchaseStatus.SHARES_RELEASED
        req.created_at = 0.0
        failed = self.orch.cleanup_stale(stale_timeout=1)
        assert failed == 0  # Terminal states are not affected


class TestSignalIdValidation:
    """Signal IDs must not contain ':' or other special chars."""

    def setup_method(self) -> None:
        self.store = ShareStore()
        self.orch = PurchaseOrchestrator(self.store)

    def test_valid_signal_id(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        req = self.orch.initiate("sig-1", "0xBuyer", "DK")
        assert req.status == PurchaseStatus.CHECKING_AVAILABILITY

    def test_signal_id_with_colon_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid signal_id"):
            self.orch.initiate("sig:evil", "0xBuyer", "DK")

    def test_signal_id_with_slash_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid signal_id"):
            self.orch.initiate("sig/path", "0xBuyer", "DK")

    def test_signal_id_with_spaces_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid signal_id"):
            self.orch.initiate("sig id", "0xBuyer", "DK")

    def test_empty_signal_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid signal_id"):
            self.orch.initiate("", "0xBuyer", "DK")
