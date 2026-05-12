"""Tests for the purchase odds ledger (per-line BPA/WPA storage)."""

from __future__ import annotations

import pytest

from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger


@pytest.fixture
def ledger() -> PurchaseOddsLedger:
    return PurchaseOddsLedger(":memory:")


class TestRecordAndGet:
    def test_roundtrip_basic(self, ledger: PurchaseOddsLedger) -> None:
        ledger.record(
            signal_id="sig-1",
            buyer_address="0xAbCd12340000000000000000000000000000Beef",
            bpas=[1_910_000, 2_000_000, 1_850_000],
            wpas=[1_800_000, 1_900_000, 1_750_000],
            bpa_mode=True,
        )
        record = ledger.get("sig-1", "0xAbCd12340000000000000000000000000000Beef")
        assert record is not None
        assert record.signal_id == "sig-1"
        # Stored lowercased for consistent matching
        assert record.buyer_address == "0xabcd12340000000000000000000000000000beef"
        assert record.bpa_mode is True
        assert record.bpas == [1_910_000, 2_000_000, 1_850_000]
        assert record.wpas == [1_800_000, 1_900_000, 1_750_000]
        assert record.recorded_at > 0

    def test_get_missing_returns_none(self, ledger: PurchaseOddsLedger) -> None:
        assert ledger.get("nonexistent", "0x0") is None

    def test_buyer_lookup_case_insensitive(self, ledger: PurchaseOddsLedger) -> None:
        buyer_upper = "0xABCD0000000000000000000000000000ABCD0000"
        buyer_lower = buyer_upper.lower()
        ledger.record(
            signal_id="sig-1",
            buyer_address=buyer_upper,
            bpas=[1_910_000],
            wpas=[1_800_000],
            bpa_mode=False,
        )
        r1 = ledger.get("sig-1", buyer_upper)
        r2 = ledger.get("sig-1", buyer_lower)
        assert r1 is not None
        assert r2 is not None
        assert r1.buyer_address == r2.buyer_address

    def test_wpa_mode_stored(self, ledger: PurchaseOddsLedger) -> None:
        ledger.record(
            signal_id="sig-wpa",
            buyer_address="0x1111111111111111111111111111111111111111",
            bpas=[1_910_000],
            wpas=[1_800_000],
            bpa_mode=False,
        )
        record = ledger.get("sig-wpa", "0x1111111111111111111111111111111111111111")
        assert record is not None
        assert record.bpa_mode is False

    def test_empty_vectors_stored(self, ledger: PurchaseOddsLedger) -> None:
        # Edge case: legacy signal with no per-line data.
        ledger.record(
            signal_id="sig-legacy",
            buyer_address="0x2222222222222222222222222222222222222222",
            bpas=[],
            wpas=[],
            bpa_mode=True,
        )
        record = ledger.get("sig-legacy", "0x2222222222222222222222222222222222222222")
        assert record is not None
        assert record.bpas == []
        assert record.wpas == []


class TestIdempotency:
    """A second record() call for the same (signal, buyer) must not
    overwrite the first. The earlier recording is authoritative."""

    def test_duplicate_record_ignored(self, ledger: PurchaseOddsLedger) -> None:
        buyer = "0x3333333333333333333333333333333333333333"
        ledger.record(
            signal_id="sig-dup",
            buyer_address=buyer,
            bpas=[1_910_000],
            wpas=[1_800_000],
            bpa_mode=True,
        )
        first = ledger.get("sig-dup", buyer)
        assert first is not None
        first_recorded_at = first.recorded_at

        # Attempt to overwrite with different values
        ledger.record(
            signal_id="sig-dup",
            buyer_address=buyer,
            bpas=[2_500_000],  # different!
            wpas=[2_400_000],  # different!
            bpa_mode=False,  # different!
        )
        second = ledger.get("sig-dup", buyer)
        assert second is not None
        assert second.bpas == [1_910_000]  # still the first recording
        assert second.wpas == [1_800_000]
        assert second.bpa_mode is True
        assert second.recorded_at == first_recorded_at

    def test_different_buyers_same_signal(self, ledger: PurchaseOddsLedger) -> None:
        ledger.record(
            signal_id="sig-multi",
            buyer_address="0xAAAA000000000000000000000000000000000000",
            bpas=[1_910_000],
            wpas=[1_800_000],
            bpa_mode=True,
        )
        ledger.record(
            signal_id="sig-multi",
            buyer_address="0xBBBB000000000000000000000000000000000000",
            bpas=[2_000_000],
            wpas=[1_900_000],
            bpa_mode=False,
        )
        assert ledger.count() == 2


class TestGetAllForSignal:
    def test_returns_ordered_by_recorded_at(self, ledger: PurchaseOddsLedger) -> None:
        buyers = [
            "0xAAAA000000000000000000000000000000000000",
            "0xBBBB000000000000000000000000000000000000",
            "0xCCCC000000000000000000000000000000000000",
        ]
        for buyer in buyers:
            ledger.record(
                signal_id="sig-audit",
                buyer_address=buyer,
                bpas=[1_910_000],
                wpas=[1_800_000],
                bpa_mode=True,
            )
        records = ledger.get_all_for_signal("sig-audit")
        assert len(records) == 3
        # Buyers are stored lowercased
        assert [r.buyer_address for r in records] == [b.lower() for b in buyers]
        # recorded_at should be non-decreasing
        assert records[0].recorded_at <= records[1].recorded_at <= records[2].recorded_at

    def test_empty_when_no_records(self, ledger: PurchaseOddsLedger) -> None:
        assert ledger.get_all_for_signal("nonexistent") == []

    def test_filters_to_signal(self, ledger: PurchaseOddsLedger) -> None:
        ledger.record(
            signal_id="sig-a",
            buyer_address="0xAAAA000000000000000000000000000000000000",
            bpas=[1_910_000],
            wpas=[1_800_000],
            bpa_mode=True,
        )
        ledger.record(
            signal_id="sig-b",
            buyer_address="0xAAAA000000000000000000000000000000000000",
            bpas=[2_000_000],
            wpas=[1_900_000],
            bpa_mode=True,
        )
        records_a = ledger.get_all_for_signal("sig-a")
        records_b = ledger.get_all_for_signal("sig-b")
        assert len(records_a) == 1
        assert len(records_b) == 1
        assert records_a[0].bpas == [1_910_000]
        assert records_b[0].bpas == [2_000_000]


class TestInputValidation:
    def test_mismatched_vector_lengths_rejected(self, ledger: PurchaseOddsLedger) -> None:
        with pytest.raises(ValueError, match="equal length"):
            ledger.record(
                signal_id="sig-bad",
                buyer_address="0x0000000000000000000000000000000000000000",
                bpas=[1, 2, 3],
                wpas=[1, 2],
                bpa_mode=True,
            )

    def test_empty_signal_id_rejected(self, ledger: PurchaseOddsLedger) -> None:
        with pytest.raises(ValueError, match="required"):
            ledger.record(
                signal_id="",
                buyer_address="0x0000000000000000000000000000000000000000",
                bpas=[],
                wpas=[],
                bpa_mode=True,
            )

    def test_empty_buyer_rejected(self, ledger: PurchaseOddsLedger) -> None:
        with pytest.raises(ValueError, match="required"):
            ledger.record(
                signal_id="sig-1",
                buyer_address="",
                bpas=[],
                wpas=[],
                bpa_mode=True,
            )


class TestCount:
    def test_count_starts_zero(self, ledger: PurchaseOddsLedger) -> None:
        assert ledger.count() == 0

    def test_count_increments(self, ledger: PurchaseOddsLedger) -> None:
        for i in range(5):
            ledger.record(
                signal_id=f"sig-{i}",
                buyer_address=f"0x{'0' * 39}{i}",
                bpas=[1_910_000],
                wpas=[1_800_000],
                bpa_mode=True,
            )
        assert ledger.count() == 5
