import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def get_fallback_weights_from_db(validator_db) -> Optional[Dict[str, float]]:
    if validator_db is None:
        logger.warning("No validator DB available for fallback")
        return None

    try:
        from .validation import validate_ema_scores

        fallback_scores = validator_db.get_latest_scores()
        if not fallback_scores:
            logger.warning("No scores in DB for fallback")
            return None

        validated_scores = validate_ema_scores(fallback_scores)
        if not validated_scores:
            logger.warning("No valid scores in DB fallback")
            return None

        total_score = sum(validated_scores.values())
        if total_score <= 0:
            logger.warning("Total score is zero or negative, cannot normalize")
            return None

        fallback_weights = {
            hotkey: score / total_score for hotkey, score in validated_scores.items()
        }

        logger.info(
            f"Loaded fallback weights for {len(fallback_weights)} miners from DB "
            f"(API data unavailable)"
        )

        return fallback_weights

    except Exception as e:
        logger.error(f"Failed to load fallback scores from DB: {e}")
        return None
