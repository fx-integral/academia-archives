import logging
import math
from typing import Dict

logger = logging.getLogger(__name__)


def validate_ema_scores(raw_scores: Dict[str, float]) -> Dict[str, float]:
    if not raw_scores:
        return {}

    validated_scores = {}
    invalid_count = 0

    for hotkey, score in raw_scores.items():

        if score < 0:
            logger.warning(
                f"Invalid score for {hotkey}: negative value {score}, skipping"
            )
            invalid_count += 1
            continue

        if not math.isfinite(score):
            logger.warning(
                f"Invalid score for {hotkey}: non-finite value {score}, skipping"
            )
            invalid_count += 1
            continue

        validated_scores[hotkey] = score

    if invalid_count > 0:
        logger.warning(f"Filtered {invalid_count} invalid scores from database")

    return validated_scores
