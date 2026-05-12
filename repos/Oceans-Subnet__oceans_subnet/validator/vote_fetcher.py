"""
Simple HTTP client that fetches the most‑recent α‑Stake vote snapshots
and exposes them to the running validator.

Responsibilities
----------------
• Fetch votes via :class:`api.client.VoteAPIClient`
• Aggregate *stake‑weighted* subnet weights so Σ = 1.0 (for logging/diagnostics)
• Return the raw :class:`api.schemas.Vote` objects to the caller

Note: All caching/persistence has been removed.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import List, Optional

import bittensor as bt

from api.client import VoteAPIClient
from api.schemas import Vote

# --------------------------------------------------------------------------- #
# Module‑level logger
# --------------------------------------------------------------------------- #
log = logging.getLogger(__name__)


class VoteFetcher:
    """
    Entry‑point invoked once per epoch by the validator scheduler.
    Stateless: simply fetches and returns the latest votes.
    """

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        *,
        api_client: Optional[VoteAPIClient] = None,  # injectable for tests
    ) -> None:
        self._api = api_client or VoteAPIClient()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def fetch_and_store(self) -> List[Vote]:
        """
        Fetch → aggregate/normalise (for logs only) → return raw votes.

        Returns
        -------
        List[Vote]
            The latest vote objects from the API.
        """
        # 1️⃣  Fetch ---------------------------------------------------------
        votes: List[Vote] = self._api.get_latest_votes()
        bt.logging.info(f"[VoteFetcher] Fetched {len(votes)} votes")
        log.info("Fetched %d votes", len(votes))

        if not votes:
            bt.logging.warning("[VoteFetcher] Empty vote list – all weights = 0")
            return []

        # 2️⃣  Aggregate *stake‑weighted* subnet weights (diagnostics) -------
        raw_weights = defaultdict(float)
        for v in votes:
            stake = float(v.voter_stake)
            for sid, w in v.weights.items():
                raw_weights[int(sid)] += float(w) * stake

        total_weight: float = sum(raw_weights.values())
        bt.logging.info(
            f"[VoteFetcher] Aggregated stake‑weighted weights for "
            f"{len(raw_weights)} subnets (Σ = {total_weight:.6f})"
        )

        # 3️⃣  Normalise so Σ = 1.0 (if possible) ---------------------------
        if total_weight > 0.0:
            norm_weights = {sid: w / total_weight for sid, w in raw_weights.items()}
        else:
            bt.logging.warning(
                "[VoteFetcher] Total stake‑weighted mass is zero – "
                "all subnets will receive 0 reward weight"
            )
            norm_weights = {}

        # 4️⃣  Debug preview -------------------------------------------------
        preview = [
            (v.voter_hotkey[:6] + "…", v.voter_stake, list(v.weights.items())[:3])
            for v in votes[:5]
        ]
        bt.logging.info(
            "[VoteFetcher] First 5 voters preview (hotkey‑truncated): %s", preview
        )
        bt.logging.debug("[VoteFetcher] Normalised master preview: %s", list(norm_weights.items())[:5])

        # 5️⃣  Return raw votes ---------------------------------------------
        return votes
