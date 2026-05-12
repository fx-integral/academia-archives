"""Unit tests for BPA/WPA executability and lockedOdds computation.

These tests lock in the canonical design from
`project_bpa_wpa_design.md`: the committed price is a limit order,
executability is uniform across modes, and WPA filters out sub-committed
prices before aggregating. They use no network, no file I/O, no fixtures
beyond pure Python values so they run in a few milliseconds.

See also: test_api.py for the higher-level check-odds endpoint tests.
"""

from __future__ import annotations

import pytest

from djinn_validator.utils.odds_logic import (
    LineOddsResult,
    american_to_decimal,
    compute_line_odds,
)


class TestAmericanToDecimal:
    """The price-conversion helper used by check-odds to parse stored
    ParsedPick.odds (int American) into decimals suitable for
    comparison with live market prices."""

    def test_zero_sentinel(self) -> None:
        assert american_to_decimal(0) == 0.0

    def test_negative_favorite(self) -> None:
        # -110 means risk 110 to win 100. Payout multiplier ~1.909.
        assert american_to_decimal(-110) == pytest.approx(1.9090909, rel=1e-6)

    def test_positive_underdog(self) -> None:
        # +150 means risk 100 to win 150. Payout multiplier = 2.5.
        assert american_to_decimal(150) == 2.5

    def test_heavy_favorite(self) -> None:
        assert american_to_decimal(-200) == pytest.approx(1.5, rel=1e-6)

    def test_heavy_underdog(self) -> None:
        assert american_to_decimal(300) == 4.0


class TestComputeLineOddsEmptyPrices:
    def test_no_books_returns_not_executable(self) -> None:
        result = compute_line_odds([], committed_decimal=1.9)
        assert result == LineOddsResult(bpa=0.0, wpa=0.0, executable=False)

    def test_no_books_legacy_signal_not_executable(self) -> None:
        # Even legacy signals need at least one book to be executable.
        result = compute_line_odds([], committed_decimal=0.0)
        assert result.executable is False


class TestComputeLineOddsLegacyFallback:
    """Legacy signals stored pick.odds as 0 ('no price recorded').
    For those, we fall back to permissive 'any price is executable'
    and do not apply any committed-price floor."""

    def test_single_book_legacy(self) -> None:
        result = compute_line_odds([1.5], committed_decimal=0.0)
        assert result.executable is True
        assert result.bpa == 1.5
        assert result.wpa == 1.5

    def test_multi_book_legacy_uses_raw_min_max(self) -> None:
        # Without a committed floor there is nothing to filter by, so
        # WPA is the literal min(prices).
        result = compute_line_odds([1.3, 1.5, 1.8], committed_decimal=0.0)
        assert result.executable is True
        assert result.bpa == 1.8
        assert result.wpa == 1.3


class TestComputeLineOddsExecutability:
    """Executability is uniform across BPA and WPA modes. The line is
    executable iff at least one book is at or above committed."""

    def test_single_book_above_committed(self) -> None:
        # Committed 1.80, only book at 1.90 -> executable.
        result = compute_line_odds([1.90], committed_decimal=1.80)
        assert result.executable is True
        assert result.bpa == 1.90
        assert result.wpa == 1.90

    def test_single_book_at_committed(self) -> None:
        # Committed 1.80, only book at exactly 1.80 -> executable.
        result = compute_line_odds([1.80], committed_decimal=1.80)
        assert result.executable is True
        assert result.bpa == 1.80
        assert result.wpa == 1.80

    def test_single_book_below_committed(self) -> None:
        # Committed 1.80, only book at 1.70 -> NOT executable.
        result = compute_line_odds([1.70], committed_decimal=1.80)
        assert result.executable is False

    def test_mixed_one_book_above_one_below(self) -> None:
        # At least one book above committed -> executable.
        result = compute_line_odds([1.70, 1.90], committed_decimal=1.80)
        assert result.executable is True

    def test_all_books_below_committed(self) -> None:
        result = compute_line_odds(
            [1.60, 1.65, 1.70],
            committed_decimal=1.80,
        )
        assert result.executable is False


class TestComputeLineOddsBPAMode:
    """BPA = best price in the surviving set. Equivalent to max(prices)
    because the max is always in the survivor set whenever any book
    meets committed."""

    def test_bpa_is_max_of_all_books_when_executable(self) -> None:
        # Books at 1.70 (filtered), 1.85, 2.00. Committed 1.80.
        # Surviving: 1.85, 2.00. BPA = max = 2.00.
        result = compute_line_odds(
            [1.70, 1.85, 2.00],
            committed_decimal=1.80,
        )
        assert result.bpa == 2.00
        assert result.executable is True

    def test_bpa_equals_committed_when_one_book_exactly(self) -> None:
        result = compute_line_odds([1.80], committed_decimal=1.80)
        assert result.bpa == 1.80


class TestComputeLineOddsWPAMode:
    """WPA = worst price in the surviving set. Filters out books below
    committed BEFORE taking the min, so WPA is always bounded below by
    committed when the line is executable. This is the key correctness
    property that user clarified 2026-04-11."""

    def test_wpa_filters_below_committed_user_lakers_example(self) -> None:
        """User's Lakers -3.5 at -130 with books at -140, -130, -120, -110.

        Committed decimal for -130 ≈ 1.7692. Books in decimal:
          -140 -> 1.7143 (below committed, filtered out)
          -130 -> 1.7692 (== committed, kept)
          -120 -> 1.8333 (kept)
          -110 -> 1.9091 (kept)

        Surviving set: {1.7692, 1.8333, 1.9091}
        BPA = 1.9091 (the -110 book, the most generous)
        WPA = 1.7692 (the -130 book, exactly committed; the -140 book
                     is NOT pulling WPA down because it was filtered).
        """
        committed = american_to_decimal(-130)
        result = compute_line_odds(
            [
                american_to_decimal(-140),  # below committed, filtered
                american_to_decimal(-130),  # at committed
                american_to_decimal(-120),
                american_to_decimal(-110),  # most favorable
            ],
            committed_decimal=committed,
        )
        assert result.executable is True
        assert result.bpa == pytest.approx(american_to_decimal(-110), rel=1e-6)
        assert result.wpa == pytest.approx(american_to_decimal(-130), rel=1e-6)

    def test_wpa_is_never_below_committed_when_executable(self) -> None:
        # 100 trials of random prices around committed. If any book is
        # at or above committed, WPA must be at or above committed.
        import random

        rng = random.Random(0xBEEF)
        committed = 1.75
        for _ in range(100):
            prices = [rng.uniform(1.4, 2.2) for _ in range(rng.randint(1, 6))]
            result = compute_line_odds(prices, committed_decimal=committed)
            if result.executable:
                assert result.wpa >= committed, f"WPA {result.wpa} below committed {committed} for " f"prices {prices}"

    def test_bpa_wpa_zeroed_when_not_executable(self) -> None:
        # No book at or above committed. Both aggregates are zeroed so
        # the UI cannot display a sub-committed fallback price as "best
        # available", and MPC settlement vectors cannot commit one as
        # lockedOdds. The buyer sees "line not available" instead.
        result = compute_line_odds(
            [1.50, 1.60, 1.70],
            committed_decimal=1.80,
        )
        assert result.executable is False
        assert result.bpa == 0.0
        assert result.wpa == 0.0

    def test_wpa_not_pulled_below_committed_by_rogue_book(self) -> None:
        # Single high-outlier book above committed, several rogue books
        # far below. The below-committed books do NOT affect WPA.
        result = compute_line_odds(
            [1.2, 1.3, 1.4, 1.9],  # only 1.9 survives if committed=1.75
            committed_decimal=1.75,
        )
        assert result.executable is True
        assert result.bpa == 1.9
        assert result.wpa == 1.9  # only one surviving price
