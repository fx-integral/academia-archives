import os
import numpy as np
from typing import Tuple, List, Union, Any, Optional
import bittensor
from numpy import ndarray, dtype, floating, complexfloating

U16_MAX = 65535

def convert_weights_and_uids_for_emit(
    uids: np.ndarray, weights: np.ndarray, label: Optional[str] = None
) -> Tuple[List[int], List[int]]:
    r"""Converts weights into integer u32 representation that sum to MAX_INT_WEIGHT.
    Args:
        uids (:obj:`np.ndarray,`):
            Array of uids as destinations for passed weights.
        weights (:obj:`np.ndarray,`):
            Array of weights.
    Returns:
        weight_uids (List[int]):
            Uids as a list.
        weight_vals (List[int]):
            Weights as a list.
    """
    # Checks.
    uids = np.asarray(uids)
    weights = np.asarray(weights)

    # Get non-zero weights and corresponding uids
    non_zero_weights = weights[weights > 0]
    non_zero_weight_uids = uids[weights > 0]

    # Debugging information
    prefix = f"[{label}] " if label else ""
    bittensor.logging.debug(f"{prefix}weights: {weights}")
    bittensor.logging.debug(f"{prefix}non_zero_weights: {non_zero_weights}")
    bittensor.logging.debug(f"{prefix}uids: {uids}")
    bittensor.logging.debug(f"{prefix}non_zero_weight_uids: {non_zero_weight_uids}")

    if np.min(weights) < 0:
        raise ValueError(
            "Passed weight is negative cannot exist on chain {}".format(
                weights
            )
        )
    if np.min(uids) < 0:
        raise ValueError(
            "Passed uid is negative cannot exist on chain {}".format(uids)
        )
    if len(uids) != len(weights):
        raise ValueError(
            "Passed weights and uids must have the same length, got {} and {}".format(
                len(uids), len(weights)
            )
        )
    if np.sum(weights) == 0:
        bittensor.logging.debug(f"{prefix}nothing to set on chain")
        return [], []  # Nothing to set on chain.
    else:
        # Preserve raw magnitudes; do not rescale by max
        weights = [float(value) for value in weights]
        bittensor.logging.debug(
            f"{prefix}emitting raw weights (no rescale): {weights}"
        )

    weight_vals = []
    weight_uids = []
    for i, (weight_i, uid_i) in enumerate(list(zip(weights, uids))):
        uint16_val = round(
            float(weight_i) * int(U16_MAX)
        )  # convert to int representation.

        # Filter zeros
        if uint16_val != 0:  # Filter zeros
            weight_vals.append(uint16_val)
            weight_uids.append(uid_i)
    bittensor.logging.debug(f"{prefix}final params: {weight_uids} : {weight_vals}")
    try:
        bittensor.logging.info(
            "On-chain uint16 weights (uid, uint16): "
            + str(list(zip(list(map(int, weight_uids)), list(map(int, weight_vals)))))
        )
    except Exception:
        pass
    return weight_uids, weight_vals


def process_weights_for_netuid(
    uids,
    weights: np.ndarray,
    netuid: int,
    subtensor: "bittensor.subtensor",
    metagraph: "bittensor.metagraph" = None,
    exclude_quantile: int = 0,
    label: Optional[str] = None,
    mechid: int = 0,
) -> Union[
    tuple[
        ndarray[Any, dtype[Any]],
        Union[
            Union[
                ndarray[Any, dtype[floating[Any]]],
                ndarray[Any, dtype[complexfloating[Any, Any]]],
            ],
            Any,
        ],
    ],
    tuple[ndarray[Any, dtype[Any]], ndarray],
    tuple[Any, ndarray],
]:
    prefix = f"[{label}] " if label else ""

    def _debug(msg: str, *values) -> None:
        if values:
            bittensor.logging.debug(prefix + msg, *values)
        else:
            bittensor.logging.debug(prefix + msg)

    def _info(msg: str) -> None:
        bittensor.logging.info(prefix + msg)

    def _warning(msg: str) -> None:
        bittensor.logging.warning(prefix + msg)

    _debug("process_weights_for_netuid()")
    _debug("weights", weights)
    _debug("netuid", netuid)
    _debug("subtensor", subtensor)
    _debug("metagraph", metagraph)
    _debug("mechid", mechid)

    # Get latest metagraph from chain if metagraph is None.
    if metagraph is None:
        try:
            metagraph = subtensor.metagraph(netuid=netuid, mechid=mechid)
        except TypeError:
            # Fallback for legacy interface without mechid support.
            metagraph = subtensor.metagraph(netuid)

    # Cast weights to floats.
    if not isinstance(weights, np.ndarray):
        weights = np.array(weights, dtype=np.float32)
    elif weights.dtype != np.float32:
        weights = weights.astype(np.float32)

    # Log each miner's raw score prior to any normalization or filtering.
    try:
        _info("Pre-normalization miner scores (uid, hotkey, score):")
        # Ensure we can index hotkeys safely
        metagraph_n = int(metagraph.n.item() if hasattr(metagraph.n, "item") else metagraph.n)
        for uid, score in zip(np.asarray(uids, dtype=int).tolist(), weights.tolist()):
            hotkey = None
            if 0 <= uid < metagraph_n and hasattr(metagraph, "hotkeys"):
                try:
                    hotkey = metagraph.hotkeys[uid]
                except Exception:
                    hotkey = None
            if hotkey is None:
                _info(f"uid={uid} score={float(score):.6f}")
            else:
                _info(f"uid={uid} hotkey={hotkey} score={float(score):.6f}")
    except Exception as e:
        # Don't break weight setting if logging fails.
        _warning(f"Failed to log pre-normalization scores: {e}")

    # Helper to log the final weights that will be emitted
    def _log_emitted_weights(log_uids: np.ndarray, log_weights: np.ndarray):
        try:
            _info("Emitted weights (uid, hotkey, weight):")
            metagraph_n_local = int(
                metagraph.n.item() if hasattr(metagraph.n, "item") else metagraph.n
            )
            for uid, w in zip(
                np.asarray(log_uids, dtype=int).tolist(),
                np.asarray(log_weights, dtype=float).tolist(),
            ):
                hotkey = None
                if 0 <= uid < metagraph_n_local and hasattr(metagraph, "hotkeys"):
                    try:
                        hotkey = metagraph.hotkeys[uid]
                    except Exception:
                        hotkey = None
                if hotkey is None:
                    _info(f"uid={uid} weight={float(w):.6f}")
                else:
                    _info(f"uid={uid} hotkey={hotkey} weight={float(w):.6f}")
        except Exception as e:
            _warning(f"Failed to log emitted weights: {e}")

    # Testing shortcut removed: proceed with normal scoring and normalization.

    # Network configuration parameters from the subtensor.
    # These are informative now; we avoid sum-normalization and preserve raw magnitudes.
    quantile = exclude_quantile / U16_MAX
    try:
        min_allowed_weights = subtensor.min_allowed_weights(netuid=netuid, mechid=mechid)
    except TypeError:
        min_allowed_weights = subtensor.min_allowed_weights(netuid=netuid)

    try:
        max_weight_limit = subtensor.max_weight_limit(netuid=netuid, mechid=mechid)
    except TypeError:
        max_weight_limit = subtensor.max_weight_limit(netuid=netuid)
    _debug("quantile", quantile)
    _debug("min_allowed_weights", min_allowed_weights)
    _debug("max_weight_limit", max_weight_limit)

    # Fallback helper: assign full weight to UID 0 (owner) when no miners have
    # positive scores.
    def _fallback_owner_only_weights() -> Tuple[np.ndarray, np.ndarray]:
        metagraph_n = int(metagraph.n.item() if hasattr(metagraph.n, "item") else metagraph.n)
        if metagraph_n <= 0:
            empty = np.zeros(0, dtype=np.float32)
            return empty, empty

        fallback_weights = np.zeros(metagraph_n, dtype=np.float32)
        owner_uid = 0
        if owner_uid < metagraph_n:
            fallback_weights[owner_uid] = 1.0

        final_uids_local = np.arange(len(fallback_weights))
        _log_emitted_weights(final_uids_local, fallback_weights)
        return final_uids_local, fallback_weights

    # Find all non zero weights.
    non_zero_weight_idx = np.argwhere(weights > 0).squeeze()
    non_zero_weight_idx = np.atleast_1d(non_zero_weight_idx)
    non_zero_weight_uids = uids[non_zero_weight_idx]
    non_zero_weights = weights[non_zero_weight_idx]
    if non_zero_weights.size == 0 or metagraph.n < min_allowed_weights:
        _warning("No non-zero weights available; falling back to owner-only weight.")
        return _fallback_owner_only_weights()

    elif non_zero_weights.size < min_allowed_weights:
        _warning("Insufficient non-zero weights; falling back to owner-only weight.")
        return _fallback_owner_only_weights()

    _debug("non_zero_weights", non_zero_weights)

    # Compute the exclude quantile and find the weights in the lowest quantile
    max_exclude = max(0, len(non_zero_weights) - min_allowed_weights) / len(
        non_zero_weights
    )
    exclude_quantile = min([quantile, max_exclude])
    lowest_quantile = np.quantile(non_zero_weights, exclude_quantile)
    _debug("max_exclude", max_exclude)
    _debug("exclude_quantile", exclude_quantile)
    _debug("lowest_quantile", lowest_quantile)

    # Exclude all weights below the allowed quantile.
    non_zero_weight_uids = non_zero_weight_uids[
        lowest_quantile <= non_zero_weights
    ]
    non_zero_weights = non_zero_weights[lowest_quantile <= non_zero_weights]
    _debug("non_zero_weight_uids", non_zero_weight_uids)
    _debug("non_zero_weights", non_zero_weights)

    # Preserve raw magnitudes (no rescale or normalization)
    _debug("final_weights_raw", non_zero_weights)
    _log_emitted_weights(non_zero_weight_uids, non_zero_weights)
    return non_zero_weight_uids, non_zero_weights
