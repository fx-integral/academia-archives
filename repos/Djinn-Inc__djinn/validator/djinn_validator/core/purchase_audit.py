"""Validator-side independent observation of which signal lines are available.

The purpose of this module is to give the purchase request handler a way to
*independently* compute which line indices are available at the buyer's
preferred sportsbooks, rather than trusting the buyer's claim. Trusting the
buyer's claim opens the oracle attack: a malicious buyer can submit several
purchases with carefully chosen `available_indices` subsets and binary-search
the real signal index by observing which submissions complete vs. fail.

The defense is to query the miner network independently for the same signal,
compute the executable line set against the buyer's books, and reject any
purchase whose claimed `available_indices` is not a subset of what the
validator observes.

This module deliberately avoids the platform Odds API. Per
`feedback_platform_api_not_for_purchases`, the platform Odds API must NOT be
used for purchase verification, only for genius decoy generation. Independent
observation here goes through the miner network, the same path that
check_odds uses.
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

log = structlog.get_logger()


@dataclass
class ObservedAvailability:
    """The validator's independent view of which line indices are available.

    `observed_indices` is the set of 1-based line indices the validator
    sees as executable at the buyer's books at the moment of observation.

    `source` is "miner" if at least one miner returned data, "stored" if
    the validator fell back to its locally-stored line prices because no
    miner was reachable, or "empty" if there is genuinely nothing to see
    (signal not registered, no lines, etc.).

    `executable_indices_per_book` is a debug aid: which indices were
    executable at each individual book the buyer requested. Not used in
    the cross-check itself, but recorded in audit logs for fraud analysis.
    """

    observed_indices: set[int]
    source: str
    line_count: int
    executable_indices_per_book: dict[str, set[int]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return len(self.observed_indices) == 0


@dataclass
class CrossCheckResult:
    """Result of comparing the buyer's claimed available_indices against the
    validator's observed_indices.

    `verdict` is one of:
        - "pass": claim is a subset of observation. Allowed.
        - "narrowed": claim is a proper subset of observation. Allowed,
          but logged. The buyer chose to ignore some available lines,
          which is their prerogative but slightly suspicious in volume.
        - "claim_extends_beyond_observation": claim contains indices the
          validator does not see as available. REJECT — possible oracle
          attack or stale buyer-side cache.
        - "validator_blind": validator could not observe anything (miner
          outage, signal not registered locally). FALL BACK to the buyer's
          claim with a warning, since refusing all purchases during a
          miner outage would deny service to honest buyers.
    """

    verdict: str
    claimed_indices: set[int]
    observed: ObservedAvailability
    extra_in_claim: set[int]
    missing_from_claim: set[int]

    @property
    def allow_purchase(self) -> bool:
        return self.verdict in ("pass", "narrowed", "validator_blind")

    @property
    def is_attack_signal(self) -> bool:
        return self.verdict == "claim_extends_beyond_observation"


async def observe_available_indices(
    signal_id: str,
    buyer_books: list[str],
    *,
    outcome_attestor: Any,
    neuron: Any,
    max_miners: int = 10,
    miner_timeout: float = 10.0,
) -> ObservedAvailability:
    """Independently query the miner network for which line indices are
    currently available at any of the buyer's preferred sportsbooks.

    Returns an empty ObservedAvailability with source="empty" if the signal
    is not registered locally. Returns source="stored" if the validator
    fell back to stored line prices because no miner returned data.
    """

    signal_meta = outcome_attestor.get_signal(signal_id)
    if signal_meta is None:
        return ObservedAvailability(observed_indices=set(), source="empty", line_count=0)

    line_count = len(signal_meta.lines)
    if line_count == 0:
        return ObservedAvailability(observed_indices=set(), source="empty", line_count=0)

    candidate_lines: list[dict[str, Any]] = []
    for i, pick in enumerate(signal_meta.lines):
        candidate_lines.append(
            {
                "index": i + 1,
                "sport": signal_meta.sport,
                "event_id": signal_meta.event_id,
                "home_team": signal_meta.home_team,
                "away_team": signal_meta.away_team,
                "market": pick.market,
                "line": pick.line,
                "side": pick.team if pick.market in ("spreads", "h2h") else pick.side,
            }
        )

    miner_data: list[dict[str, Any]] = []
    miner_source = "stored"

    if neuron:
        miner_uids = neuron.get_miner_uids()
        if miner_uids:
            random.shuffle(miner_uids)
            targets: list[tuple[int, str]] = []
            for uid in miner_uids:
                axon = neuron.get_axon_info(uid)
                ip = axon.get("ip", "")
                port = axon.get("port", 0)
                if not ip or not port or ip in ("0.0.0.0", "127.0.0.1"):
                    continue
                targets.append((uid, f"http://{ip}:{port}/v1/check"))
                if len(targets) >= max_miners:
                    break

            if targets:
                from djinn_validator.api.middleware import create_signed_headers

                body = json.dumps({"lines": candidate_lines}).encode()
                auth_headers: dict[str, str] = {}
                if neuron.wallet:
                    auth_headers = create_signed_headers("/v1/check", body, neuron.wallet)

                async def _query(uid: int, url: str) -> tuple[int, dict[str, Any] | None]:
                    try:
                        async with httpx.AsyncClient() as client:
                            resp = await client.post(
                                url,
                                content=body,
                                headers={"Content-Type": "application/json", **auth_headers},
                                timeout=miner_timeout,
                            )
                        if resp.status_code != 200:
                            return (uid, None)
                        data = resp.json()
                        if data.get("api_error") and not data.get("results"):
                            return (uid, None)
                        return (uid, data)
                    except Exception as e:
                        log.warning(
                            "purchase_audit_miner_failed",
                            miner_uid=uid,
                            error=str(e)[:100],
                        )
                        return (uid, None)

                results = await asyncio.gather(*[_query(uid, url) for uid, url in targets])
                for _uid, data in results:
                    if data and data.get("results"):
                        miner_data.append(data)

    if miner_data:
        miner_source = "miner"

    return _compute_observed_indices(
        signal_meta=signal_meta,
        miner_data=miner_data,
        buyer_books=buyer_books,
        line_count=line_count,
        miner_source=miner_source,
    )


def _compute_observed_indices(
    *,
    signal_meta: Any,
    miner_data: list[dict[str, Any]],
    buyer_books: list[str],
    line_count: int,
    miner_source: str,
) -> ObservedAvailability:
    """Pure function: given miner responses and signal metadata, compute
    which 1-based line indices are executable at any of the buyer's books.

    Pulled out as a separate helper so it is testable without the network.
    """

    from djinn_validator.utils.odds_logic import (
        american_to_decimal as _american_to_decimal,
    )
    from djinn_validator.utils.odds_logic import (
        compute_line_odds as _compute_line_odds,
    )

    buyer_books_lower = {b.lower() for b in buyer_books} if buyer_books else set()

    merged_by_index: dict[int, list[dict[str, Any]]] = {}
    for data in miner_data:
        for lr in data.get("results", []):
            idx = lr.get("index")
            if idx is None:
                continue
            merged_by_index.setdefault(idx, []).extend(lr.get("bookmakers", []))

    observed: set[int] = set()
    per_book: dict[str, set[int]] = {b.lower(): set() for b in buyer_books or []}

    for i, pick in enumerate(signal_meta.lines):
        idx = i + 1
        bm_results = merged_by_index.get(idx, [])

        # When the buyer didn't specify books, fall back to ALL books
        # observed by miners. This matches the permissive default of the
        # current purchase flow.
        if buyer_books_lower:
            filtered = [bm for bm in bm_results if bm.get("bookmaker", "").lower() in buyer_books_lower]
        else:
            filtered = bm_results

        committed_decimal = _american_to_decimal(pick.odds) if pick.odds else 0.0

        if filtered:
            prices = [bm["odds"] for bm in filtered if bm.get("odds")]
            if prices:
                result = _compute_line_odds(prices, committed_decimal)
                if result.executable:
                    observed.add(idx)
                for bm in filtered:
                    book = bm.get("bookmaker", "").lower()
                    price = bm.get("odds")
                    if not book or not price:
                        continue
                    single_book_result = _compute_line_odds([price], committed_decimal)
                    if single_book_result.executable:
                        per_book.setdefault(book, set()).add(idx)
                continue

        # Fallback when miners returned no data for this line. Mirror
        # check_odds behavior: if we are entirely in stored-fallback mode
        # (no miners reachable for ANY line), trust the stored price.
        # Otherwise treat the line as unavailable here, even if the
        # stored price would qualify, because we cannot confirm it is
        # currently live at the buyer's books.
        if miner_source == "stored":
            stored_price = pick.odds or 0
            if stored_price:
                dec = _american_to_decimal(stored_price)
                stored_result = _compute_line_odds([dec], committed_decimal)
                if stored_result.executable:
                    observed.add(idx)

    return ObservedAvailability(
        observed_indices=observed,
        source=miner_source if miner_data else ("stored" if miner_source == "stored" else "empty"),
        line_count=line_count,
        executable_indices_per_book=per_book,
    )


def cross_check(
    *,
    claimed_indices: list[int] | set[int],
    observed: ObservedAvailability,
) -> CrossCheckResult:
    """Compare a buyer's claimed available_indices against what the
    validator independently observed. The verdict drives whether the
    purchase should be allowed."""

    claim_set: set[int] = set(claimed_indices)

    if observed.source == "empty":
        return CrossCheckResult(
            verdict="validator_blind",
            claimed_indices=claim_set,
            observed=observed,
            extra_in_claim=set(),
            missing_from_claim=set(),
        )

    if not observed.observed_indices and observed.source != "miner":
        return CrossCheckResult(
            verdict="validator_blind",
            claimed_indices=claim_set,
            observed=observed,
            extra_in_claim=set(),
            missing_from_claim=set(),
        )

    extra = claim_set - observed.observed_indices
    missing = observed.observed_indices - claim_set

    if extra:
        return CrossCheckResult(
            verdict="claim_extends_beyond_observation",
            claimed_indices=claim_set,
            observed=observed,
            extra_in_claim=extra,
            missing_from_claim=missing,
        )

    if missing:
        return CrossCheckResult(
            verdict="narrowed",
            claimed_indices=claim_set,
            observed=observed,
            extra_in_claim=set(),
            missing_from_claim=missing,
        )

    return CrossCheckResult(
        verdict="pass",
        claimed_indices=claim_set,
        observed=observed,
        extra_in_claim=set(),
        missing_from_claim=set(),
    )
