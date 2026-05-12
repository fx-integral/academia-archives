import logging
import math
import os
import torch
from typing import Dict, List, Optional, Any

from ..utils.miners import build_uid_to_hotkey, is_valid_hotkey
from .models import ValidationRecord

logger = logging.getLogger(__name__)

USE_EQUAL_WEIGHTS_FALLBACK = (
    os.getenv("USE_EQUAL_WEIGHTS_FALLBACK", "false").lower() == "true"
)
MIN_WIN_RATE = 0.0

# Burn mechanism: percentage of emissions that go to miners vs owner
# Hardcoded to 0.5 = 25% to miners, 75% to owner (ensures validator consensus)
MINER_EMISSION_PERCENTAGE = 0.25
BURN_RATE = 1.0 - MINER_EMISSION_PERCENTAGE  # 0.75 = 75% burn rate

# Owner/Validator UID that receives the burned portion (25% of emissions)
OWNER_UID = 176


def _is_finite_number(value: float) -> bool:
    return math.isfinite(value)


def _validate_response(response: Any) -> bool:
    if response is None:
        logger.debug("Response is None (likely timeout or missing)")
        return False

    if not hasattr(response, "prob_yes") or not hasattr(response, "prob_no"):
        logger.debug("Response missing required fields: prob_yes or prob_no")
        return False

    try:
        prob_yes = float(response.prob_yes)
        prob_no = float(response.prob_no)

        if not _is_finite_number(prob_yes):
            logger.debug(f"prob_yes is not finite: {prob_yes}")
            return False

        if not _is_finite_number(prob_no):
            logger.debug(f"prob_no is not finite: {prob_no}")
            return False

        if not (0.0 <= prob_yes <= 1.0):
            logger.debug(f"prob_yes out of range [0.0, 1.0]: {prob_yes}")
            return False

        epsilon = 1e-6
        if abs((prob_yes + prob_no) - 1.0) > epsilon:
            logger.debug(
                f"prob_yes + prob_no != 1.0: {prob_yes} + {prob_no} = {prob_yes + prob_no}"
            )
            return False

        if hasattr(response, "event_id") and response.event_id is not None:
            if (
                not isinstance(response.event_id, str)
                or len(response.event_id.strip()) == 0
            ):
                logger.debug(f"event_id is invalid: {response.event_id}")
                return False

        if hasattr(response, "confidence") and response.confidence is not None:
            try:
                confidence = float(response.confidence)
                if not _is_finite_number(confidence):
                    logger.debug(f"confidence is not finite: {confidence}")
                    return False
                if not (0.0 <= confidence <= 1.0):
                    logger.debug(f"confidence out of range [0.0, 1.0]: {confidence}")
                    return False
            except (ValueError, TypeError):
                logger.debug(
                    f"confidence cannot be converted to float: {response.confidence}"
                )
                return False

        if (
            hasattr(response, "protocol_version")
            and response.protocol_version is not None
        ):
            if not isinstance(response.protocol_version, (str, int)):
                logger.debug(
                    f"protocol_version has invalid type: {type(response.protocol_version)}"
                )
                return False

        return True
    except (ValueError, TypeError, AttributeError) as exc:
        logger.debug(f"Response validation error: {exc}")
        return False


def _check_thresholds(record: ValidationRecord) -> tuple[bool, Optional[str]]:
    if not record or not record.performance:
        return False, "missing validation data"

    perf = record.performance

    profit = perf.profit
    if profit is None or profit <= 0:
        return False, f"profit not positive (profit={profit})"

    win_rate = perf.win_rate
    if win_rate is not None and win_rate < MIN_WIN_RATE:
        return (
            False,
            f"win_rate below threshold (win_rate={win_rate}, min={MIN_WIN_RATE})",
        )

    return True, None


def _get_hotkey_from_uid(
    uid: int, metagraph: Any, uid_to_hotkey: Optional[Dict[int, str]] = None
) -> Optional[str]:
    if uid_to_hotkey is not None and uid in uid_to_hotkey:
        hotkey = uid_to_hotkey[uid]
        if is_valid_hotkey(hotkey):
            return hotkey

    try:
        if hasattr(metagraph, "hotkeys") and uid < len(metagraph.hotkeys):
            hotkey = metagraph.hotkeys[uid]
            if is_valid_hotkey(hotkey):
                return str(hotkey).strip()
    except (IndexError, AttributeError, TypeError):
        pass

    return None


def reward(
    responses: List[Any],
    uids: List[int],
    metagraph: Any,
    wahoo_weights: Optional[Dict[str, float]] = None,
    wahoo_validation_data: Optional[List[Any]] = None,
    uid_to_hotkey: Optional[Dict[int, str]] = None,
) -> torch.FloatTensor:
    if not uids or len(uids) == 0:
        return torch.FloatTensor([])

    if len(responses) != len(uids):
        logger.warning(
            f"Mismatch: {len(responses)} responses for {len(uids)} UIDs. "
            "Returning zero rewards."
        )
        return torch.zeros(len(uids), dtype=torch.float32)

    if uid_to_hotkey is None:
        logger.debug("Building uid_to_hotkey mapping from metagraph")
        uid_to_hotkey = build_uid_to_hotkey(metagraph, active_uids=uids)

    rewards_dict: Dict[int, float] = {}

    if wahoo_weights is None:
        wahoo_weights = {}

    validation_by_hotkey: Dict[str, ValidationRecord] = {}
    if wahoo_validation_data:
        for record in wahoo_validation_data:
            if isinstance(record, ValidationRecord):
                validation_by_hotkey[record.hotkey] = record

    for idx, uid in enumerate(uids):
        response = responses[idx] if idx < len(responses) else None
        hotkey = _get_hotkey_from_uid(uid, metagraph, uid_to_hotkey)

        if hotkey is None or not is_valid_hotkey(hotkey):
            logger.warning(
                f"UID {uid}: missing or invalid hotkey. Setting weight to 0.0"
            )
            rewards_dict[uid] = 0.0
            continue

        if hotkey in wahoo_weights:
            weight = wahoo_weights[hotkey]
            try:
                weight_float = float(weight)
                if weight_float >= 0.0:
                    validation_record = validation_by_hotkey.get(hotkey)
                    if validation_record:
                        passes, reason = _check_thresholds(validation_record)
                        if not passes:
                            logger.warning(
                                f"UID {uid} (hotkey={hotkey}): "
                                f"failing thresholds - {reason}. Setting weight to 0.0"
                            )
                            rewards_dict[uid] = 0.0
                        else:
                            rewards_dict[uid] = weight_float
                    else:
                        rewards_dict[uid] = weight_float
                    continue
            except (ValueError, TypeError):
                pass

        if _validate_response(response):
            validation_record = validation_by_hotkey.get(hotkey)
            if validation_record:
                passes, reason = _check_thresholds(validation_record)
                if not passes:
                    logger.warning(
                        f"UID {uid} (hotkey={hotkey}): "
                        f"failing thresholds - {reason}. Setting weight to 0.0"
                    )
                    rewards_dict[uid] = 0.0
                else:
                    rewards_dict[uid] = 1.0
            else:
                rewards_dict[uid] = 1.0
        else:
            validation_record = validation_by_hotkey.get(hotkey)
            if validation_record:
                passes, reason = _check_thresholds(validation_record)
                if not passes:
                    logger.warning(
                        f"UID {uid} (hotkey={hotkey}): "
                        f"failing thresholds - {reason}. Setting weight to 0.0"
                    )
                else:
                    logger.debug(
                        f"UID {uid} (hotkey={hotkey}): "
                        "invalid response. Setting weight to 0.0"
                    )
            else:
                logger.debug(
                    f"UID {uid} (hotkey={hotkey}): "
                    "missing validation data and invalid response. Setting weight to 0.0"
                )
            rewards_dict[uid] = 0.0

    rewards = torch.FloatTensor([rewards_dict.get(uid, 0.0) for uid in uids])

    total = rewards.sum()
    if total > 0.0:
        # Normalize to sum to 1.0 first, then scale by MINER_EMISSION_PERCENTAGE
        # This implements the burn mechanism: only MINER_EMISSION_PERCENTAGE goes to miners
        # The remaining BURN_RATE will be routed to owner UID 176
        rewards = rewards / total * MINER_EMISSION_PERCENTAGE
        logger.info(
            f"Applied {MINER_EMISSION_PERCENTAGE*100:.1f}% miner emissions "
            f"(burn_rate: {BURN_RATE*100:.1f}% will route to owner UID {OWNER_UID}). "
            f"Total weight sum: {rewards.sum().item():.6f}"
        )
    else:
        if USE_EQUAL_WEIGHTS_FALLBACK:
            valid_count = sum(1 for uid in uids if rewards_dict.get(uid, 0.0) > 0.0)
            if valid_count > 0:
                # Apply burn rate to equal weights as well
                equal_weight = (1.0 / valid_count) * MINER_EMISSION_PERCENTAGE
                rewards = torch.FloatTensor(
                    [
                        equal_weight if rewards_dict.get(uid, 0.0) > 0.0 else 0.0
                        for uid in uids
                    ]
                )
                logger.info(
                    f"All WAHOO weights zero, using equal weights fallback: "
                    f"{valid_count} miners with valid responses, weight={equal_weight:.6f} "
                    f"({MINER_EMISSION_PERCENTAGE*100:.1f}% to miners, burn_rate: {BURN_RATE*100:.1f}% to owner UID {OWNER_UID})"
                )
            else:
                rewards = torch.zeros(len(uids), dtype=torch.float32)
        else:
            rewards = torch.zeros(len(uids), dtype=torch.float32)

    assert rewards.shape == (
        len(uids),
    ), f"Rewards shape mismatch: expected ({len(uids)},), got {rewards.shape}"

    if total > 0.0:
        sum_after_norm = rewards.sum().item()
        epsilon = 1e-6
        expected_sum = MINER_EMISSION_PERCENTAGE
        if abs(sum_after_norm - expected_sum) >= epsilon:
            logger.warning(
                f"Normalization invariant violation: rewards.sum() = {sum_after_norm}, "
                f"expected {expected_sum} (tolerance: {epsilon})"
            )

    if total > 0.0 and rewards.sum().item() > 0.0:
        pass
    else:
        logger.debug(
            "Skipping set_weights() call: all rewards are zero "
            f"(total={total}, rewards.sum()={rewards.sum().item()})"
        )

    return rewards
