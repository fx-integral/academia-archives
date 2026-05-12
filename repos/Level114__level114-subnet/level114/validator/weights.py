"""Utilities for validator weight management."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import bittensor as bt

from level114.base.utils.weight_utils import process_weights_for_netuid


@dataclass
class WeightState:
    last_update: float = 0.0
    last_attempt: float = 0.0
    next_update: float = 0.0
    last_uids: Optional[np.ndarray] = None
    last_weights: Optional[np.ndarray] = None


def should_update(state: WeightState, now: float, update_interval: float) -> bool:
    if now < state.next_update:
        return False
    if state.last_update and (now - state.last_update) < update_interval:
        return False
    return True


def apply_weight_update(
    mechanism_id: int,
    mechanism_name: str,
    state: WeightState,
    scores: Dict[str, Dict[str, Any]],
    *,
    metagraph,
    subtensor,
    wallet,
    netuid: int,
    update_interval: float,
    retry_interval: float,
) -> bool:
    if not scores:
        return False

    now = time.time()
    if not should_update(state, now, update_interval):
        return False

    state.last_attempt = now
    num_nodes = int(metagraph.n.item() if hasattr(metagraph.n, "item") else metagraph.n)
    raw_weights = np.zeros(num_nodes)
    hotkey_to_uid = {axon.hotkey: uid for uid, axon in enumerate(metagraph.axons)}

    for hotkey, result in scores.items():
        uid = hotkey_to_uid.get(hotkey)
        if uid is None:
            continue
        score_value = float(result.get("score", 0))
        weight = max(min(score_value / 1000.0, 1.0), 0.0)
        raw_weights[uid] = weight

    processed_uids, processed_weights = process_weights_for_netuid(
        uids=np.arange(num_nodes),
        weights=raw_weights,
        netuid=netuid,
        subtensor=subtensor,
        metagraph=metagraph,
        label=f"{mechanism_name}#{mechanism_id}",
        mechid=mechanism_id,
    )

    if len(processed_weights) == 0 or np.sum(processed_weights) <= 0:
        bt.logging.warning(
            f"[Weights][{mechanism_name}#{mechanism_id}] No weights to set"
        )
        state.next_update = max(now + retry_interval, state.last_attempt + retry_interval)
        return False

    result = subtensor.set_weights(
        wallet=wallet,
        netuid=netuid,
        mechid=mechanism_id,
        uids=processed_uids,
        weights=processed_weights,
        # wait_for_inclusion=True,
        # wait_for_finalization=True,
    )

    success = result
    message = None
    if isinstance(result, tuple):
        if len(result) >= 1:
            success = result[0]
        if len(result) >= 2:
            message = result[1]

    if success:
        state.last_update = time.time()
        state.next_update = state.last_update + update_interval
        state.last_uids = np.copy(processed_uids)
        state.last_weights = np.copy(processed_weights)
        bt.logging.info(
            (
                "✅ [Weights][{name}#{mid}] Updated for {count} miners "
                "(total weight: {total:.3f})"
            ).format(
                name=mechanism_name,
                mid=mechanism_id,
                count=int(np.count_nonzero(processed_weights)),
                total=float(np.sum(processed_weights)),
            )
        )
        return True

    bt.logging.error(
        f"❌ [Weights][{mechanism_name}#{mechanism_id}] Failed to set weights on blockchain"
        + (f": {message}" if message else "")
    )
    state.next_update = max(now + retry_interval, state.last_attempt + retry_interval)
    return False


def apply_weight_updates(
    states: Dict[int, WeightState],
    mechanism_results: Dict[int, Dict[str, Any]],
    *,
    metagraph,
    subtensor,
    wallet,
    netuid: int,
    update_interval: float,
    retry_interval: float,
) -> Dict[int, bool]:
    updates: Dict[int, bool] = {}
    for mechanism_id, stats in mechanism_results.items():
        scores = stats.get("scoring_results") or {}
        state = states.get(mechanism_id)
        if state is None:
            updates[mechanism_id] = False
            continue
        try:
            mechanism_name = stats.get("mechanism_name", f"mechanism-{mechanism_id}")
            updated = apply_weight_update(
                mechanism_id=mechanism_id,
                mechanism_name=mechanism_name,
                state=state,
                scores=scores,
                metagraph=metagraph,
                subtensor=subtensor,
                wallet=wallet,
                netuid=netuid,
                update_interval=update_interval,
                retry_interval=retry_interval,
            )
        except Exception as exc:  # noqa: BLE001
            bt.logging.error(
                f"Error applying weights for mechanism {mechanism_id}: {exc}"
            )
            stats["errors"] = stats.get("errors", 0) + 1
            updated = False
        stats["weights_updated"] = updated
        updates[mechanism_id] = updated
    return updates
