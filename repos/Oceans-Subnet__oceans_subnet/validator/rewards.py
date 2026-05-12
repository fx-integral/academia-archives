"""
Reward‑calculator v3.2  —  stake‑aware + liquidity‑aware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reward(N) = Σ_subnets  ( LP_N,sub / Σ LP_all,sub ) × MasterWeight_sub

Stateless version: inputs (votes, liquidity) are passed explicitly.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

import bittensor as bt
from api.schemas import Vote 


class RewardCalculator:
    """
    Computes the per‑miner reward weights for the current epoch.

    Stateless API:
      • compute(metagraph, votes, liquidity) -> {uid: weight}
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------ #
    # PUBLIC
    # ------------------------------------------------------------------ #
    def compute(
        self,
        *,
        metagraph,
        votes: List[Vote],
        liquidity: Dict[int, Dict[int, float]],
    ) -> Dict[int, float]:
        # ------------------ 0. Prepare UID universe --------------------
        uids: List[int] = list(getattr(metagraph, "uids", []))
        if not uids:
            bt.logging.warning("[RewardCalc] Metagraph contained no UIDs")
            return {}

        # ------------------ 1. Master subnet vector --------------------
        master_w = self._build_master_vector(votes)
        bt.logging.debug(
            f"[RewardCalc] Master vector: {len(master_w)} subnets, {master_w} "
            f"(Σ = {sum(master_w.values()):.6f})"
        )
        if not master_w:
            bt.logging.warning(
                "[RewardCalc] Master vector empty – all miners will be uniform"
            )

        # ------------------ 2. Liquidity map ---------------------------
        lp_map: Dict[int, Dict[int, float]] = liquidity or {}

        # ------------------ 3. Apply formula ---------------------------
        rewards: Dict[int, float] = defaultdict(float)

        for raw_sid, w_sub in master_w.items():
            # Key safety
            try:
                subnet_id = int(raw_sid)
            except Exception:
                bt.logging.debug(
                    f"[RewardCalc] Skipping non‑numeric subnet id “{raw_sid}”"
                )
                continue

            if w_sub <= 0.0:
                continue  # this subnet contributes nothing

            lp_by_uid = lp_map.get(subnet_id, {})
            total_lp = sum(lp_by_uid.values())

            bt.logging.debug(
                f"[RewardCalc] Subnet {subnet_id}: total LP={total_lp:.9f}, "
                f"weight={w_sub:.6f}"
            )

            if total_lp <= 0.0:
                # No liquidity yet — safe to skip
                continue

            inv_total_lp = 1.0 / total_lp
            for uid, lp_amt in lp_by_uid.items():
                # In case keys are str‐UIDs
                try:
                    uid_int = int(uid)
                except Exception:
                    bt.logging.debug(
                        f"[RewardCalc]    Ignoring non‑UID key “{uid}” "
                        f"on subnet {subnet_id}"
                    )
                    continue

                if lp_amt <= 0.0:
                    continue  # ignore zero positions

                contrib = lp_amt * inv_total_lp * w_sub
                rewards[uid_int] += contrib
                bt.logging.debug(
                    f"[RewardCalc]    uid {uid_int:<5} +{contrib:.9f}"
                )

        # ------------------ 4. Normalise or uniform fallback -----------
        ttl = sum(rewards.values())
        if ttl > 0.0:
            factor = 1.0 / ttl
            rewards = {uid: r * factor for uid, r in rewards.items()}
            bt.logging.info(
                f"[RewardCalc] Rewards normalised, {len(rewards)} active miners "
                f"(Σ = {sum(rewards.values()):.6f})"
            )
        else:
            bt.logging.warning(
                "[RewardCalc] Reward vector zero – using uniform distribution"
            )
            uniform = 1.0 / len(uids)
            rewards = {int(uid): uniform for uid in uids}

        bt.logging.debug(
            f"[RewardCalc] Final rewards for {len(rewards)} miners – "
            f"Σ = {sum(rewards.values()):.6f}"
        )
        return rewards

    # ------------------------------------------------------------------ #
    # INTERNAL
    # ------------------------------------------------------------------ #
    def _build_master_vector(self, votes: List[Vote]) -> Dict[int, float]:
        """
        Returns { subnet_id: weight } where Σ weights = 1.0, computed
        from current `votes`. If no votes are present, returns {} and
        the caller will fall back to uniform miner weights.
        """
        if not votes:
            return {}

        raw: Dict[int, float] = defaultdict(float)
        total_stake: float = 0.0

        for v in votes:
            stake = float(getattr(v, "voter_stake", 0.0))
            weights = getattr(v, "weights", {}) or {}
            if stake <= 0.0 or not weights:
                continue

            s = sum(weights.values())
            if s <= 0.0:
                continue

            for sid, w in weights.items():
                raw[int(sid)] += stake * (float(w) / s)

            total_stake += stake

        if total_stake <= 0.0:
            return {}

        master_w = {sid: w / total_stake for sid, w in raw.items()}
        bt.logging.info(
            f"[RewardCalc] Master subnet vector: {len(master_w)} subnets, {master_w} "
            f"(Σ = {sum(master_w.values()):.6f})"
        )
        return master_w
