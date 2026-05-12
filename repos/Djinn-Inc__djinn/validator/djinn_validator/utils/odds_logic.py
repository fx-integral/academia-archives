"""Pure helpers for BPA/WPA executability and lockedOdds computation.

These functions implement the canonical design captured in
`project_bpa_wpa_design.md` (Djinn project memory, 2026-04-11):

- The genius's committed price is a limit order. A line is executable
  iff at least one of the buyer's books offers price >= committed,
  regardless of BPA vs. WPA mode.
- BPA mode's lockedOdds = max(prices_at_buyer_books).
- WPA mode's lockedOdds = min(p for p in prices_at_buyer_books
  if p >= committed). Books below committed are filtered out before
  taking the min so WPA is always bounded below by committed.
- Legacy signals with no stored committed odds (committed_decimal == 0)
  fall back to permissive "any price is executable" for backwards
  compatibility with pre-odds-storage signals.

The logic was previously inlined in `check_odds` inside api/server.py
with a subtly wrong WPA executability rule (`min >= committed`
instead of `max >= committed`). Extracted here so the semantics can
be unit-tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass


def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal.

    Positive American: +150 -> 2.5  (1.0 + 150/100)
    Negative American: -110 -> 1.909 (1.0 + 100/110)
    Zero:  0 -> 0.0 (sentinel "no odds")
    """
    if american == 0:
        return 0.0
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


@dataclass(frozen=True)
class LineOddsResult:
    """Per-line executability and lockedOdds aggregates at a buyer's books.

    `executable` is uniform across BPA and WPA modes (only depends on
    whether max(prices) >= committed). `bpa` and `wpa` differ by the
    committed-price floor rule described in the module docstring.
    """

    bpa: float
    wpa: float
    executable: bool


def compute_line_odds(
    prices: list[float],
    committed_decimal: float,
) -> LineOddsResult:
    """Compute BPA, WPA, and executability for a single line.

    Args:
        prices: Decimal odds from the buyer's sportsbooks for this
            specific line. May be empty (no book offering it).
        committed_decimal: The genius's committed minimum decimal
            odds. Pass 0.0 for legacy signals with no stored price —
            the function then treats any available price as executable
            and does not apply any filter.

    Returns:
        LineOddsResult with executability and both aggregates. When no
        book is at or above committed, `bpa` and `wpa` are both 0 so
        callers (UI and MPC settlement vectors) cannot accidentally
        surface or commit a sub-committed price as if it were the
        locked odds.
    """
    if not prices:
        return LineOddsResult(bpa=0.0, wpa=0.0, executable=False)

    max_price = max(prices)

    # Legacy signals (no committed odds stored) fall back to the
    # permissive "any price = executable" behavior and skip the floor.
    if committed_decimal <= 0:
        return LineOddsResult(
            bpa=max_price,
            wpa=min(prices),
            executable=True,
        )

    is_executable = max_price >= committed_decimal

    above_committed = [p for p in prices if p >= committed_decimal]
    if above_committed:
        bpa = max(above_committed)
        wpa = min(above_committed)
    else:
        bpa = 0.0
        wpa = 0.0

    return LineOddsResult(bpa=bpa, wpa=wpa, executable=is_executable)
