"""
StoryNet Subnet Utility Functions
=================================

Common utilities used by both Miners and Validators.
"""

import json
import time
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime


def validate_json(json_string: str) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Validate and parse JSON string.

    Args:
        json_string: JSON string to validate

    Returns:
        Tuple of (is_valid, parsed_data)
        - is_valid: True if JSON is valid
        - parsed_data: Parsed dictionary if valid, None otherwise

    Example:
        >>> is_valid, data = validate_json('{"title": "Test"}')
        >>> if is_valid:
        ...     print(data["title"])
    """
    try:
        data = json.loads(json_string)
        return True, data
    except json.JSONDecodeError:
        return False, None


def validate_required_fields(
    data: Dict[str, Any],
    required_fields: List[str]
) -> tuple[bool, List[str]]:
    """
    Check if all required fields exist in data.

    Args:
        data: Dictionary to validate
        required_fields: List of required field names

    Returns:
        Tuple of (all_present, missing_fields)

    Example:
        >>> data = {"title": "Test", "genre": "Sci-Fi"}
        >>> is_valid, missing = validate_required_fields(data, ["title", "genre", "setting"])
        >>> print(f"Valid: {is_valid}, Missing: {missing}")
        Valid: False, Missing: ['setting']
    """
    missing = [field for field in required_fields if field not in data]
    return len(missing) == 0, missing


def stringify(obj: Any, max_length: int = 10000) -> str:
    """
    Convert any object to string for embedding/hashing.

    Args:
        obj: Object to stringify (dict, list, str, etc.)
        max_length: Maximum length of output string

    Returns:
        String representation of the object

    Example:
        >>> data = {"title": "Test", "chapters": [1, 2, 3]}
        >>> text = stringify(data)
        >>> print(text[:50])
    """
    if isinstance(obj, str):
        return obj[:max_length]
    elif isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False)[:max_length]
    else:
        return str(obj)[:max_length]


def compute_hash(data: Any) -> str:
    """
    Compute SHA256 hash of data.

    Args:
        data: Data to hash (will be stringified first)

    Returns:
        Hex string of hash

    Example:
        >>> hash1 = compute_hash({"title": "Test"})
        >>> hash2 = compute_hash({"title": "Test"})
        >>> print(hash1 == hash2)
        True
    """
    text = stringify(data)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def format_timestamp(timestamp: Optional[float] = None) -> str:
    """
    Format Unix timestamp to readable string.

    Args:
        timestamp: Unix timestamp (seconds), defaults to now

    Returns:
        Formatted string like "2025-10-16 14:30:45"

    Example:
        >>> print(format_timestamp())
        2025-10-16 14:30:45
    """
    if timestamp is None:
        timestamp = time.time()
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely divide two numbers, returning default if denominator is 0.

    Args:
        numerator: Numerator
        denominator: Denominator
        default: Value to return if division by zero

    Returns:
        Result of division or default

    Example:
        >>> print(safe_divide(10, 2))
        5.0
        >>> print(safe_divide(10, 0))
        0.0
    """
    if denominator == 0:
        return default
    return numerator / denominator


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    Clamp value between min and max.

    Args:
        value: Value to clamp
        min_val: Minimum value
        max_val: Maximum value

    Returns:
        Clamped value

    Example:
        >>> print(clamp(150, 0, 100))
        100
        >>> print(clamp(-10, 0, 100))
        0
    """
    return max(min_val, min(value, max_val))


def normalize_weights(weights: Dict[int, float]) -> Dict[int, float]:
    """
    Normalize weights to sum to 1.0.

    Args:
        weights: Dictionary of {uid: weight}

    Returns:
        Normalized weights dictionary

    Example:
        >>> weights = {1: 80, 2: 60, 3: 40}
        >>> normalized = normalize_weights(weights)
        >>> print(sum(normalized.values()))
        1.0
    """
    total = sum(weights.values())
    if total == 0:
        # Equal weights if all zero
        n = len(weights)
        return {uid: 1.0 / n for uid in weights.keys()}

    return {uid: w / total for uid, w in weights.items()}


def exponential_moving_average(
    new_value: float,
    old_value: float,
    alpha: float = 0.1
) -> float:
    """
    Calculate exponential moving average.

    EMA = α * new_value + (1-α) * old_value

    Args:
        new_value: New observation
        old_value: Previous EMA value
        alpha: Weight for new value (0-1)

    Returns:
        Updated EMA value

    Example:
        >>> ema = 70.0
        >>> ema = exponential_moving_average(80.0, ema, alpha=0.1)
        >>> print(ema)
        71.0
    """
    return alpha * new_value + (1 - alpha) * old_value


def get_field_length(data: Dict[str, Any], field: str) -> int:
    """
    Get length of a field in data (string length or array length).

    Args:
        data: Dictionary containing the field
        field: Field name to check

    Returns:
        Length of field value, or 0 if not found

    Example:
        >>> data = {"title": "Test Story", "chapters": [1, 2, 3]}
        >>> print(get_field_length(data, "title"))
        10
        >>> print(get_field_length(data, "chapters"))
        3
    """
    if field not in data:
        return 0

    value = data[field]
    if isinstance(value, (str, list)):
        return len(value)
    elif isinstance(value, dict):
        return len(json.dumps(value))
    else:
        return len(str(value))


def extract_nested_field(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """
    Extract nested field using dot notation.

    Args:
        data: Dictionary to extract from
        path: Dot-separated path (e.g., "arcs.act1.chapters")
        default: Default value if path not found

    Returns:
        Extracted value or default

    Example:
        >>> data = {"arcs": {"act1": {"chapters": ["c1", "c2"]}}}
        >>> print(extract_nested_field(data, "arcs.act1.chapters"))
        ['c1', 'c2']
        >>> print(extract_nested_field(data, "arcs.act2.chapters", default=[]))
        []
    """
    keys = path.split(".")
    current = data

    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default

    return current


class Timer:
    """
    Simple timer context manager.

    Example:
        >>> with Timer() as t:
        ...     # Do some work
        ...     time.sleep(1)
        >>> print(f"Took {t.elapsed:.2f} seconds")
        Took 1.00 seconds
    """

    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.elapsed = 0.0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.elapsed = self.end_time - self.start_time
        return False


def chunks(lst: List[Any], n: int) -> List[List[Any]]:
    """
    Split list into chunks of size n.

    Args:
        lst: List to split
        n: Chunk size

    Returns:
        List of chunks

    Example:
        >>> data = [1, 2, 3, 4, 5, 6, 7]
        >>> for chunk in chunks(data, 3):
        ...     print(chunk)
        [1, 2, 3]
        [4, 5, 6]
        [7]
    """
    return [lst[i:i + n] for i in range(0, len(lst), n)]


# Export all public functions
__all__ = [
    "validate_json",
    "validate_required_fields",
    "stringify",
    "compute_hash",
    "format_timestamp",
    "safe_divide",
    "clamp",
    "normalize_weights",
    "exponential_moving_average",
    "get_field_length",
    "extract_nested_field",
    "Timer",
    "chunks"
]
