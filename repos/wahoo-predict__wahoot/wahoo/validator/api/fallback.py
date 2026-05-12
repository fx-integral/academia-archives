import logging
from typing import List, Optional

from ..scoring.models import ValidationRecord

logger = logging.getLogger(__name__)


def has_usable_metrics(record: ValidationRecord) -> bool:
    if not record or not record.performance:
        return False

    perf = record.performance

    has_volume = perf.total_volume_usd is not None and perf.total_volume_usd > 0
    has_weighted_volume = perf.weighted_volume is not None and perf.weighted_volume > 0
    has_profit = perf.realized_profit_usd is not None
    has_trades = perf.trade_count is not None and perf.trade_count > 0

    return has_weighted_volume or has_volume or has_profit or has_trades


def filter_usable_records(records: List[ValidationRecord]) -> List[ValidationRecord]:
    if not records:
        return []

    usable = [r for r in records if has_usable_metrics(r)]
    excluded = len(records) - len(usable)

    if excluded > 0:
        logger.warning(
            f"Excluded {excluded} validation record(s) with empty metrics "
            f"({len(usable)} usable, {excluded} excluded)"
        )

    return usable


def should_skip_weight_computation(
    validation_data: Optional[List[ValidationRecord]],
    *,
    log_reason: bool = True,
) -> bool:
    if not validation_data or len(validation_data) == 0:
        if log_reason:
            logger.warning(
                "No usable validation data available after API + cache fallback. "
                "Skipping weight computation and set_weights() call."
            )
        return True

    usable_records = filter_usable_records(validation_data)
    if len(usable_records) == 0:
        if log_reason:
            logger.warning(
                f"All {len(validation_data)} validation record(s) have empty metrics. "
                "Skipping weight computation and set_weights() call."
            )
        return True

    return False


__all__ = [
    "has_usable_metrics",
    "filter_usable_records",
    "should_skip_weight_computation",
]
