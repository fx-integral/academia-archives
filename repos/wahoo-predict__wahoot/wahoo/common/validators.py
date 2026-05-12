import logging
import math
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def _is_finite_number(value: float) -> bool:
    return math.isfinite(value)


def validate_validation_record(record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        logger.debug("Record is not a dictionary")
        return False

    if "hotkey" not in record:
        logger.debug("Missing required field: hotkey")
        return False

    hotkey = record["hotkey"]
    if not isinstance(hotkey, str) or len(hotkey.strip()) == 0:
        logger.debug("hotkey is empty or not a string")
        return False

    has_performance = "performance" in record and isinstance(
        record["performance"], dict
    )
    performance = record.get("performance", {})

    required_numeric_fields = ["weighted_volume", "realized_profit_usd"]

    for field_name in required_numeric_fields:
        if has_performance:
            value = performance.get(field_name)
        else:
            value = record.get(field_name)

        if value is None:
            logger.debug(f"Missing required field: {field_name}")
            return False

        try:
            float_value = float(value)
            if not _is_finite_number(float_value):
                logger.debug(
                    f"Field {field_name} is not finite: {float_value} " f"(NaN or Inf)"
                )
                return False
        except (ValueError, TypeError):
            logger.debug(
                f"Field {field_name} cannot be converted to float: {value} (type: {type(value)})"
            )
            return False

    optional_numeric_fields = {
        "unrealized_profit_usd": (int, float, str),
        "win_rate": (int, float, str),
        "total_fees_paid_usd": (int, float, str),
        "referral_volume_usd": (int, float, str),
    }

    for field_name, field_types in optional_numeric_fields.items():
        if has_performance:
            value = performance.get(field_name)
        else:
            value = record.get(field_name)

        if value is None:
            continue

        try:
            float_value = float(value)
            if not _is_finite_number(float_value):
                logger.debug(
                    f"Optional field {field_name} is not finite: {float_value} "
                    f"(NaN or Inf)"
                )
                return False
            if field_name == "win_rate":
                if not (0.0 <= float_value <= 1.0):
                    logger.debug(f"win_rate out of range: {float_value}")
                    return False
        except (ValueError, TypeError):
            logger.debug(
                f"Optional numeric field {field_name} cannot be converted to float: {value}"
            )
            return False

    optional_int_fields = {
        "trade_count": int,
        "open_positions_count": int,
        "referral_count": int,
    }

    for field_name, field_type in optional_int_fields.items():
        if has_performance:
            value = performance.get(field_name)
        else:
            value = record.get(field_name)

        if value is None:
            continue

        try:
            int(value)
        except (ValueError, TypeError):
            logger.debug(
                f"Optional integer field {field_name} cannot be converted to int: {value}"
            )
            return False

    optional_string_fields = {
        "signature": str,
        "message": str,
        "wahoo_user_id": str,
    }

    for field_name, field_type in optional_string_fields.items():
        if field_name in record:
            value = record[field_name]
            if value is None:
                continue

            if not isinstance(value, field_type):
                logger.debug(
                    f"Optional field {field_name} has wrong type: "
                    f"{type(value)}, expected {field_type}"
                )
                return False

    last_active_timestamp = None
    if has_performance:
        last_active_timestamp = performance.get("last_active_timestamp")
    if last_active_timestamp is None:
        last_active_timestamp = record.get("last_active_timestamp")

    if last_active_timestamp is not None and not isinstance(last_active_timestamp, str):
        logger.debug(
            f"Optional field last_active_timestamp has wrong type: "
            f"{type(last_active_timestamp)}, expected str"
        )
        return False

    return True


def validate_validation_data_batch(
    data: List[Dict[str, Any]], batch_hotkeys: List[str]
) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        logger.warning("Validation data is not a list")
        return []

    valid_records: List[Dict[str, Any]] = []
    invalid_count = 0

    for record in data:
        if validate_validation_record(record):
            valid_records.append(record)
        else:
            invalid_count += 1
            hotkey = record.get("hotkey", "unknown")
            logger.warning(
                f"Invalid response structure for hotkey {hotkey}. "
                "Dropping record from batch."
            )

    if len(valid_records) == 0 and len(data) > 0:
        logger.warning(
            f"All {len(data)} records in batch failed validation. "
            f"Requested hotkeys: {batch_hotkeys[:5]}..."
        )

    if invalid_count > 0:
        logger.info(
            f"Validated batch: {len(valid_records)} valid, {invalid_count} invalid "
            f"out of {len(data)} total records"
        )

    return valid_records


def validate_events_response(data: Any) -> Optional[str]:
    if data is None:
        logger.debug("Events response is None")
        return None

    events_list = None

    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            events_list = data["data"]
        elif "events" in data and isinstance(data["events"], list):
            events_list = data["events"]
        elif "event_id" in data:
            event_id = data.get("event_id")
            if isinstance(event_id, str) and len(event_id.strip()) > 0:
                return event_id.strip()
    elif isinstance(data, list):
        events_list = data

    if events_list:
        for event in events_list:
            if not isinstance(event, dict):
                continue

            is_active = event.get("is_active", False) or event.get("status") == "active"

            if is_active and "event_id" in event:
                event_id = event.get("event_id")
                if isinstance(event_id, str) and len(event_id.strip()) > 0:
                    return event_id.strip()

            if "event_id" in event and not any(
                e.get("is_active", False) for e in events_list if isinstance(e, dict)
            ):
                event_id = event.get("event_id")
                if isinstance(event_id, str) and len(event_id.strip()) > 0:
                    return event_id.strip()

    logger.debug("No valid active event_id found in events response")
    return None
