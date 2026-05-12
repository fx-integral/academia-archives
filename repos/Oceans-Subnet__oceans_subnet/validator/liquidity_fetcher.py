"""
Validator‑side helper that pulls liquidity data from chain and returns an
in‑memory map for reward calculation.

All amounts are denominated in **TAO**.
No storage/caching/persistence is performed.
"""
from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict
from typing import Awaitable, Callable, Dict, List, Optional

import bittensor as bt
from bittensor import AsyncSubtensor            # type: ignore
from bittensor.utils.balance import Balance
from bittensor.utils.balance import fixed_to_float

from config import settings
from utils.liquidity_utils import (
    LiquiditySubnet,
    fetch_subnet_liquidity_positions,
)
from utils.subnet_utils import get_metagraph

log = logging.getLogger("validator.liquidity_fetcher")


class LiquidityFetcher:
    """
    Fetches on‑chain liquidity and returns:

        { liquidity_subnet_id: { uid_on_primary: tao, … }, … }

    **Important note**: we do not sum `position.liquidity` (Uniswap "L").
    We compute token amounts at the current subnet price via
    `LiquidityPosition.to_token_amounts(price)` and count **only TAO**.
    """

    # --- Optional policy knobs (you can tune these) -------------------- #
    MIN_RELATIVE_WIDTH: float = float(getattr(settings, "MIN_RELATIVE_WIDTH", 0.0))
    COUNT_ONLY_IN_RANGE: bool = bool(getattr(settings, "COUNT_ONLY_IN_RANGE", True))

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        *,
        primary_netuid: int,   # ← validator’s own subnet (e.g., 66)
        fetch_fn: Optional[
            Callable[..., Awaitable[List[LiquiditySubnet]]]
        ] = None,
    ) -> None:
        self.primary_netuid = int(primary_netuid)
        self._fetch_fn = fetch_fn or self._default_fetch

        # Cache inside the fetcher: coldkey → UID (on primary subnet)
        self._primary_uid_map: Dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # PUBLIC – async entry‑point                                         #
    # ------------------------------------------------------------------ #
    async def fetch_and_store(
        self,
        *,
        netuid: Optional[int] = None,
        block: Optional[int] = None,
    ) -> Dict[int, Dict[int, float]]:
        """
        Returns
        -------
        Dict[int, Dict[int, float]]
            {subnet_id: {uid_on_primary: tao_value, ...}, ...}
        """
        if netuid == 0:
            bt.logging.warning("[LiquidityFetcher] Ignoring request for subnet 0")
            return {}

        bt.logging.info(f"[LiquidityFetcher] Fetching liquidity (netuid={netuid})…")

        # 1️⃣  Download liquidity ----------------------------------------
        if asyncio.iscoroutinefunction(self._fetch_fn):
            liquidity_subnets = await self._fetch_fn(netuid=netuid, block=block)
        else:
            liquidity_subnets = await asyncio.to_thread(
                self._fetch_fn, netuid=netuid, block=block
            )

        bt.logging.info(
            f"[LiquidityFetcher] Retrieved {len(liquidity_subnets)} "
            f"LiquiditySubnet objects"
        )

        # 2️⃣  Ensure primary‑subnet UID map is loaded once --------------
        await self._load_primary_uid_map(block=block)

        # 2.5️⃣ Fetch current prices once per subnet ---------------------
        subnet_ids = [ls.netuid for ls in liquidity_subnets]
        bt.logging.warning(
            f"[LiquidityFetcher] Fetching current prices, block={block}"
        )
        price_map = await self._fetch_current_prices(subnet_ids, block=block)
        bt.logging.warning(f"[LiquidityFetcher] Prices: {price_map}")
        if not price_map:
            bt.logging.warning(
                "[LiquidityFetcher] No current prices available; all contributions will be 0."
            )

        # 3️⃣  Aggregate TAO per coldkey / subnet ------------------------
        # (internal aggregation keyed by (coldkey, subnet))
        aggregated: Dict[tuple, float] = {}

        for ls in liquidity_subnets:
            P = price_map.get(ls.netuid, 0.0)
            if not (P and P > 0.0 and math.isfinite(P)):
                bt.logging.warning(
                    f"[LiquidityFetcher] No valid price for subnet {ls.netuid}; skipping."
                )
                continue

            P_bal = Balance.from_tao(P)

            bt.logging.warning(
                f"[LiquidityFetcher] Subnet {ls.netuid} → "
                f"{ls.unique_coldkeys} coldkeys, {ls.total_positions} positions (P={P:.10f})"
            )

            for coldkey, positions in ls.coldkey_positions.items():
                tao_sum = 0.0

                for idx, pos in enumerate(positions, start=1):
                    pos_ctx = f"subnet {ls.netuid} | coldkey {coldkey[:6]}… | pos#{idx}"

                    # Start analysis for this position
                    bt.logging.warning(f"[LiquidityFetcher] Analyzing position {pos_ctx}")

                    # Defensive guards against invalid/degenerate ranges
                    try:
                        p_low = float(pos.price_low)
                        p_high = float(pos.price_high)
                    except Exception as e:
                        bt.logging.warning(
                            f"[LiquidityFetcher] Discard position ({pos_ctx}): "
                            f"failed to read price bounds: {e}"
                        )
                        continue

                    if not (math.isfinite(p_low) and math.isfinite(p_high)):
                        bt.logging.warning(
                            f"[LiquidityFetcher] Discard position ({pos_ctx}): "
                            f"non‑finite bounds low={p_low}, high={p_high}"
                        )
                        continue
                    if p_low <= 0.0 or p_high <= 0.0:
                        bt.logging.warning(
                            f"[LiquidityFetcher] Discard position ({pos_ctx}): "
                            f"non‑positive bounds low={p_low}, high={p_high}"
                        )
                        continue
                    if p_high <= p_low:
                        bt.logging.warning(
                            f"[LiquidityFetcher] Discard position ({pos_ctx}): "
                            f"degenerate range (high ≤ low) low={p_low}, high={p_high}"
                        )
                        continue

                    # Optional: only reward *active* liquidity
                    if self.COUNT_ONLY_IN_RANGE and not (p_low < P < p_high):
                        bt.logging.warning(
                            f"[LiquidityFetcher] Discard position ({pos_ctx}): "
                            f"out of range at P={P:.10f} (low={p_low}, high={p_high})"
                        )
                        continue

                    # Optional: enforce minimal band width (as fraction of current price)
                    if self.MIN_RELATIVE_WIDTH > 0.0:
                        rel_width = (p_high - p_low) / P
                        if rel_width < self.MIN_RELATIVE_WIDTH:
                            bt.logging.warning(
                                f"[LiquidityFetcher] Discard position ({pos_ctx}): "
                                f"relative width {rel_width:.6f} < "
                                f"min {self.MIN_RELATIVE_WIDTH:.6f}"
                            )
                            continue

                    # Compute token amounts at current price and take **only TAO**
                    try:
                        _alpha_amt, tao_amt = pos.to_token_amounts(P_bal)
                    except Exception as e:
                        bt.logging.warning(
                            f"[LiquidityFetcher] Discard position ({pos_ctx}): "
                            f"to_token_amounts() failed: {e}"
                        )
                        continue

                    tao_val = self._bal_to_tao(tao_amt)
                    tao_sum += tao_val

                    bt.logging.warning(
                        f"[LiquidityFetcher] Accepted position ({pos_ctx}): "
                        f"contributes {tao_val:.9f} TAO at P={P:.10f} "
                        f"(low={p_low}, high={p_high})"
                    )

                if tao_sum > 0.0:
                    aggregated[(coldkey, ls.netuid)] = aggregated.get(
                        (coldkey, ls.netuid), 0.0
                    ) + tao_sum
                    bt.logging.warning(
                        f"[LiquidityFetcher] Coldkey {coldkey[:6]}… subtotal on subnet {ls.netuid}: "
                        f"{tao_sum:.9f} TAO"
                    )
                else:
                    bt.logging.warning(
                        f"[LiquidityFetcher] Coldkey {coldkey[:6]}… subtotal on subnet {ls.netuid}: "
                        f"0.000000000 TAO (no accepted positions or zero contribution)"
                    )

        bt.logging.warning(f"[LiquidityFetcher] Aggregated entries: {len(aggregated)}")

        # 4️⃣  Build liquidity map for RewardCalculator ------------------
        liq_map: Dict[int, Dict[int, float]] = defaultdict(dict)

        for (ck, subnet), tao_val in aggregated.items():
            if tao_val <= 0.0:
                continue
            uid = self._primary_uid_map.get(ck)
            if uid is None:
                bt.logging.debug(
                    f"[LiquidityFetcher] Coldkey {ck[:6]}… not on subnet "
                    f"{self.primary_netuid} – skipped"
                )
                continue
            liq_map[int(subnet)][int(uid)] = float(tao_val)
            bt.logging.warning(
                f"[LiquidityFetcher] Map entry: subnet {subnet} uid {uid} "
                f"→ {tao_val:.9f} TAO"
            )

        bt.logging.warning(
            f"[LiquidityFetcher] liquidity map built "
            f"({sum(len(v) for v in liq_map.values())} UIDs total) "
            f"liq_map={liq_map}"
        )
        return liq_map

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _bal_to_tao(b: Balance) -> float:
        """
        Best‑effort conversion of a Balance to TAO as float.
        Works whether Balance carries tao/rao or raises on float().
        """
        try:
            return float(b)  # preferred: Balance.__float__ should yield TAO
        except Exception:
            try:
                return float(getattr(b, "tao"))
            except Exception:
                try:
                    rao = float(getattr(b, "rao"))
                    return rao / 1e9
                except Exception:
                    return 0.0

    async def _default_fetch(
        self,
        *,
        netuid: Optional[int],
        block: Optional[int],
    ) -> List[LiquiditySubnet]:
        async with AsyncSubtensor(network=settings.BITTENSOR_NETWORK) as subtensor:
            return await fetch_subnet_liquidity_positions(
                subtensor,
                netuid=netuid,
                block=block,
                max_concurrency=settings.MAX_CONCURRENCY,
                logprogress=False,
            )

    async def _fetch_current_prices(
        self, subnets: List[int], *, block: Optional[int]
    ) -> Dict[int, float]:
        """
        Read current price per subnet from `Swap.AlphaSqrtPrice` and square it:
            P = (AlphaSqrtPrice)**2

        Returns: {netuid: price_float}
        """
        prices: Dict[int, float] = {}
        if not subnets:
            return prices

        async with AsyncSubtensor(network=settings.BITTENSOR_NETWORK) as st:
            try:
                block_hash = await st.determine_block_hash(
                    block=block, block_hash=None, reuse_block=(block is None)
                )
            except Exception:
                block_hash = None

            async def _one(uid: int):
                try:
                    sp = await st.substrate.query(
                        module="Swap",
                        storage_function="AlphaSqrtPrice",
                        params=[uid],
                        block_hash=block_hash,
                    )
                    sqrt_p = fixed_to_float(sp)
                    P = float(sqrt_p) * float(sqrt_p)
                    if math.isfinite(P) and P > 0.0:
                        return uid, P
                except Exception as e:
                    bt.logging.debug(
                        f"[LiquidityFetcher] AlphaSqrtPrice query failed for {uid}: {e}"
                    )
                return uid, 0.0

            results = await asyncio.gather(*(_one(u) for u in set(subnets)))
            for uid, P in results:
                if P > 0.0:
                    prices[uid] = P

        return prices

    # ---------- UID map (coldkey → UID on primary subnet) -------------- #
    async def _load_primary_uid_map(self, *, block: Optional[int]) -> None:
        bt.logging.warning(
            f"[LiquidityFetcher] Loading UID map for subnet {self.primary_netuid}"
        )
        async with AsyncSubtensor(network=settings.BITTENSOR_NETWORK) as subtensor:
            mg = await get_metagraph(
                self.primary_netuid, st=subtensor, lite=True, block=block
            )
            self._primary_uid_map = {
                str(ck): int(uid) for uid, ck in zip(mg.uids, mg.coldkeys)
            }
        bt.logging.warning(
            f"[LiquidityFetcher] UID map loaded ({len(self._primary_uid_map)} entries)"
        )
