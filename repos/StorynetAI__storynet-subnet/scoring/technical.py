"""
Technical Score Module
======================

Calculates Technical Score (30 points) based on:
1. JSON format validity (10 points)
2. Schema/field completeness (10 points)
3. Response time (10 points)

This is 100% objective and programmable.
"""

import json
from typing import Dict, Any, List, Tuple
import bittensor as bt


def calculate_technical_score(
    response_json: str,
    generation_time: float,
    task_type: str,
    required_fields: List[str]
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate technical score for a miner's response.

    Args:
        response_json: JSON string response from miner
        generation_time: Time taken to generate (seconds)
        task_type: Type of task ("blueprint"|"characters"|"story_arc"|"chapters")
        required_fields: List of required field names

    Returns:
        Tuple of (score, breakdown)
        - score: Total technical score (0-30)
        - breakdown: Dictionary with detailed scores

    Example:
        >>> score, breakdown = calculate_technical_score(
        ...     '{"title": "Test"}',
        ...     25.0,
        ...     "blueprint",
        ...     ["title", "genre", "setting"]
        ... )
        >>> print(score)
        18.33
    """
    breakdown = {
        "json_valid": 0.0,
        "schema_complete": 0.0,
        "response_time": 0.0
    }

    # 1. JSON Format Validity (10 points)
    try:
        data = json.loads(response_json)
        breakdown["json_valid"] = 10.0
    except json.JSONDecodeError as e:
        bt.logging.error(f"Invalid JSON: {e}")
        # JSON invalid = 0 total score
        return 0.0, breakdown

    # 2. Schema Completeness (10 points)
    schema_score = calculate_schema_score(data, required_fields, task_type)
    breakdown["schema_complete"] = schema_score

    # 3. Response Time (10 points)
    time_score = calculate_time_score(generation_time)
    breakdown["response_time"] = time_score

    # Total score
    total = sum(breakdown.values())

    return min(total, 30.0), breakdown


def calculate_schema_score(
    data: Dict[str, Any],
    required_fields: List[str],
    task_type: str
) -> float:
    """
    Calculate schema completeness score (10 points).

    Args:
        data: Parsed JSON data
        required_fields: List of required field names
        task_type: Task type for validation

    Returns:
        Schema score (0-10)
    """
    if not required_fields:
        return 10.0

    # Check field existence
    missing_fields = [field for field in required_fields if field not in data]

    if not missing_fields:
        # All fields present - check types
        type_score = validate_field_types(data, task_type)
        return 10.0 * type_score
    else:
        # Partial credit for partial completion
        matched = len(required_fields) - len(missing_fields)
        total = len(required_fields)
        return 10.0 * (matched / total) if total > 0 else 0.0


def validate_field_types(data: Dict[str, Any], task_type: str) -> float:
    """
    Validate that fields have correct types.

    Args:
        data: Parsed JSON data
        task_type: Task type

    Returns:
        Type validation score (0.0-1.0)
    """
    correct_types = 0
    total_checks = 0

    if task_type == "blueprint":
        checks = [
            ("title", str),
            ("genre", str),
            ("setting", str),
            ("core_conflict", str),
            ("themes", list),
            ("tone", str),
            ("target_audience", str)
        ]

        for field, expected_type in checks:
            if field in data:
                total_checks += 1
                if isinstance(data[field], expected_type):
                    correct_types += 1

                # Additional check for themes array
                if field == "themes" and isinstance(data[field], list):
                    if 2 <= len(data[field]) <= 5:
                        correct_types += 0.5  # Bonus for correct length

    elif task_type == "characters":
        if "characters" in data and isinstance(data["characters"], list):
            total_checks = 1
            if len(data["characters"]) == 5:
                correct_types = 1.0
            else:
                # Partial credit
                correct_types = min(len(data["characters"]) / 5, 1.0)

    elif task_type == "story_arc":
        checks = [
            ("title", str),
            ("description", str),
            ("chapters", list),
            ("arcs", dict),
            ("themes", dict),
            ("hooks", dict)
        ]

        for field, expected_type in checks:
            if field in data:
                total_checks += 1
                if isinstance(data[field], expected_type):
                    correct_types += 1

        # Additional check for 12 chapters
        if "chapters" in data and isinstance(data["chapters"], list):
            if len(data["chapters"]) == 12:
                correct_types += 1.0

    elif task_type == "chapters":
        if "chapters" in data and isinstance(data["chapters"], list):
            total_checks = 1
            all_valid = True
            for chapter in data["chapters"]:
                if not isinstance(chapter, dict):
                    all_valid = False
                    break
                # Check required fields
                if "id" not in chapter or "title" not in chapter or "content" not in chapter:
                    all_valid = False
                    break

            if all_valid:
                correct_types = 1.0

    return correct_types / total_checks if total_checks > 0 else 0.0


def calculate_time_score(generation_time: float) -> float:
    """
    Calculate response time score (10 points).

    Args:
        generation_time: Time taken in seconds

    Returns:
        Time score (0-10)

    Scoring:
        - < 30s: 10 points
        - 30-60s: 10 - (time - 30) * 0.33
        - > 60s: 0 points
    """
    if generation_time <= 30:
        return 10.0
    elif generation_time <= 60:
        # Linear decay from 10 to 0
        return max(0, 10.0 - (generation_time - 30) * 0.33)
    else:
        return 0.0


def validate_json_structure(
    data: Dict[str, Any],
    task_type: str
) -> Tuple[bool, str]:
    """
    Deep validation of JSON structure.

    Args:
        data: Parsed JSON data
        task_type: Task type

    Returns:
        Tuple of (is_valid, error_message)
    """
    if task_type == "blueprint":
        if "themes" in data:
            if not isinstance(data["themes"], list):
                return False, "themes must be an array"
            if len(data["themes"]) < 2:
                return False, "themes must have at least 2 elements"

    elif task_type == "characters":
        if "characters" not in data:
            return False, "Missing 'characters' array"

        if not isinstance(data["characters"], list):
            return False, "'characters' must be an array"

        if len(data["characters"]) != 5:
            return False, "Must have exactly 5 characters"

        required_ids = {"protagonist", "ally", "rival", "mentor", "wildcard"}
        character_ids = {ch.get("id") for ch in data["characters"] if isinstance(ch, dict)}

        if not required_ids.issubset(character_ids):
            missing = required_ids - character_ids
            return False, f"Missing character IDs: {missing}"

    elif task_type == "story_arc":
        if "chapters" not in data:
            return False, "Missing 'chapters' array"

        if not isinstance(data["chapters"], list):
            return False, "'chapters' must be an array"

        if len(data["chapters"]) != 12:
            return False, f"Must have 12 chapters, got {len(data['chapters'])}"

        # Check story_progress values
        for i, chapter in enumerate(data["chapters"]):
            if "storyProgress" not in chapter:
                return False, f"Chapter {i+1} missing 'storyProgress'"

            progress = chapter["storyProgress"]
            if not isinstance(progress, (int, float)):
                return False, f"Chapter {i+1} storyProgress must be a number"

            if i == 0 and not (0.05 <= progress <= 0.10):
                return False, f"First chapter storyProgress should be ~0.08, got {progress}"

            if i == 11 and not (0.95 <= progress <= 1.0):
                return False, f"Last chapter storyProgress should be ~1.0, got {progress}"

    elif task_type == "chapters":
        if "chapters" not in data:
            return False, "Missing 'chapters' array"

        if not isinstance(data["chapters"], list):
            return False, "'chapters' must be an array"

        for i, chapter in enumerate(data["chapters"]):
            if not isinstance(chapter, dict):
                return False, f"Chapter {i+1} must be an object"

            # Check required fields
            required = ["id", "title", "content", "choices"]
            for field in required:
                if field not in chapter:
                    return False, f"Chapter {i+1} missing '{field}'"

            # Check content length
            content = chapter.get("content", "")
            if len(content) < 1000:
                return False, f"Chapter {i+1} content too short ({len(content)} < 1000 chars)"

            # Check choices
            choices = chapter.get("choices", [])
            if not isinstance(choices, list):
                return False, f"Chapter {i+1} choices must be an array"

            if not (2 <= len(choices) <= 4):
                return False, f"Chapter {i+1} must have 2-4 choices, got {len(choices)}"

    return True, ""


# Export functions
__all__ = [
    "calculate_technical_score",
    "calculate_schema_score",
    "calculate_time_score",
    "validate_field_types",
    "validate_json_structure"
]
