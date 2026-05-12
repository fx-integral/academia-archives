"""
Structure Score Module
======================

Calculates Structure Score (40 points) based on:
- Field completeness and relationships
- Story arc logic (chapter progression, act structure)
- Character relationships and diversity
- Content length and quality indicators

This is based on rules and algorithms, objective and quantifiable.
"""

import json
from typing import Dict, Any, List, Tuple
import bittensor as bt


def calculate_structure_score(
    data: Dict[str, Any],
    task_type: str
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate structure score for a miner's response.

    Args:
        data: Parsed JSON data
        task_type: Type of task

    Returns:
        Tuple of (score, breakdown)
        - score: Total structure score (0-40)
        - breakdown: Dictionary with detailed scores
    """
    breakdown = {}

    if task_type == "blueprint":
        score, breakdown = score_blueprint_structure(data)
    elif task_type == "characters":
        score, breakdown = score_characters_structure(data)
    elif task_type == "story_arc":
        score, breakdown = score_story_arc_structure(data)
    elif task_type == "chapters":
        score, breakdown = score_chapters_structure(data)
    else:
        return 0.0, {}

    return min(score, 40.0), breakdown


def score_blueprint_structure(data: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """
    Score blueprint structure (40 points).

    Breakdown:
    - Field completeness: 20 points
    - Content length appropriateness: 10 points
    - Themes count: 10 points
    """
    breakdown = {
        "field_completeness": 0.0,
        "content_length": 0.0,
        "themes_count": 0.0
    }

    # Field completeness (20 points)
    required_fields = ["title", "genre", "setting", "core_conflict", "themes", "tone", "target_audience"]
    present_fields = sum(1 for field in required_fields if field in data)
    breakdown["field_completeness"] = 20.0 * (present_fields / len(required_fields))

    # Content length (10 points)
    setting_len = len(data.get("setting", ""))
    conflict_len = len(data.get("core_conflict", ""))

    length_score = 0.0
    if 50 <= setting_len <= 300:
        length_score += 5.0
    elif 30 <= setting_len <= 500:
        length_score += 3.0

    if 30 <= conflict_len <= 200:
        length_score += 5.0
    elif 15 <= conflict_len <= 300:
        length_score += 3.0

    breakdown["content_length"] = length_score

    # Themes count (10 points)
    themes = data.get("themes", [])
    if isinstance(themes, list):
        if 2 <= len(themes) <= 5:
            breakdown["themes_count"] = 10.0
        elif 1 <= len(themes) <= 6:
            breakdown["themes_count"] = 5.0

    total = sum(breakdown.values())
    return total, breakdown


def score_characters_structure(data: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """
    Score characters structure (40 points).

    Breakdown:
    - 5 characters present: 20 points
    - Character completeness: 10 points
    - Relationships network: 10 points
    """
    breakdown = {
        "character_count": 0.0,
        "character_completeness": 0.0,
        "relationships": 0.0
    }

    characters = data.get("characters", [])
    if not isinstance(characters, list):
        return 0.0, breakdown

    # Character count (20 points)
    if len(characters) == 5:
        breakdown["character_count"] = 20.0
    elif len(characters) >= 3:
        breakdown["character_count"] = 20.0 * (len(characters) / 5)

    # Character completeness (10 points)
    required_char_fields = ["id", "name", "archetype", "background", "motivation", "skills", "personality_traits"]
    completeness_scores = []

    for char in characters:
        if not isinstance(char, dict):
            continue

        present = sum(1 for field in required_char_fields if field in char)
        completeness_scores.append(present / len(required_char_fields))

    if completeness_scores:
        avg_completeness = sum(completeness_scores) / len(completeness_scores)
        breakdown["character_completeness"] = 10.0 * avg_completeness

    # Relationships network (10 points)
    relationship_scores = []
    for char in characters:
        if not isinstance(char, dict):
            continue

        relationships = char.get("relationships", {})
        if isinstance(relationships, dict):
            # Check if relationships exist
            if len(relationships) >= 2:
                relationship_scores.append(1.0)
            elif len(relationships) >= 1:
                relationship_scores.append(0.5)

    if relationship_scores:
        avg_relationships = sum(relationship_scores) / len(relationship_scores)
        breakdown["relationships"] = 10.0 * avg_relationships

    total = sum(breakdown.values())
    return total, breakdown


def score_story_arc_structure(data: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """
    Score story arc structure (40 points).

    Breakdown:
    - 12 chapters: 20 points
    - Progress monotonic: 10 points
    - 4-act structure: 10 points
    """
    breakdown = {
        "chapter_count": 0.0,
        "progress_monotonic": 0.0,
        "act_structure": 0.0
    }

    # Chapter count (20 points)
    chapters = data.get("chapters", [])
    if not isinstance(chapters, list):
        return 0.0, breakdown

    if len(chapters) == 12:
        breakdown["chapter_count"] = 20.0
    elif len(chapters) >= 8:
        breakdown["chapter_count"] = 20.0 * (len(chapters) / 12)

    # Progress monotonic (10 points)
    if is_progress_monotonic(chapters):
        breakdown["progress_monotonic"] = 10.0
    else:
        # Partial credit if mostly monotonic
        violations = count_progress_violations(chapters)
        if violations <= 2:
            breakdown["progress_monotonic"] = 10.0 * (1 - violations / len(chapters))

    # Act structure (10 points)
    arcs = data.get("arcs", {})
    if validate_act_structure(arcs):
        breakdown["act_structure"] = 10.0
    else:
        # Partial credit if structure mostly correct
        act_score = score_partial_act_structure(arcs)
        breakdown["act_structure"] = 10.0 * act_score

    total = sum(breakdown.values())
    return total, breakdown


def score_chapters_structure(data: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """
    Score chapters structure (40 points).

    Breakdown:
    - Content length: 20 points
    - Choices quality: 10 points
    - Branch diversity: 10 points
    """
    breakdown = {
        "content_length": 0.0,
        "choices_quality": 0.0,
        "branch_diversity": 0.0
    }

    chapters = data.get("chapters", [])
    if not isinstance(chapters, list) or not chapters:
        return 0.0, breakdown

    # Content length (20 points)
    length_scores = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue

        content = chapter.get("content", "")
        length = len(content)

        if 1000 <= length <= 3000:
            length_scores.append(1.0)
        elif 800 <= length < 1000:
            length_scores.append(0.7)
        elif 3000 < length <= 3500:
            length_scores.append(0.8)
        elif 500 <= length < 800:
            length_scores.append(0.4)

    if length_scores:
        avg_length_score = sum(length_scores) / len(length_scores)
        breakdown["content_length"] = 20.0 * avg_length_score

    # Choices quality (10 points)
    choice_scores = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue

        choices = chapter.get("choices", [])
        if not isinstance(choices, list):
            continue

        # Check choice count (2-4 is good)
        if 2 <= len(choices) <= 4:
            choice_scores.append(1.0)
        elif len(choices) == 1:
            choice_scores.append(0.3)
        elif len(choices) > 4:
            choice_scores.append(0.6)

    if choice_scores:
        avg_choice_score = sum(choice_scores) / len(choice_scores)
        breakdown["choices_quality"] = 10.0 * avg_choice_score

    # Branch diversity (10 points)
    diversity_score = calculate_branch_diversity(chapters)
    breakdown["branch_diversity"] = 10.0 * diversity_score

    total = sum(breakdown.values())
    return total, breakdown


# Helper functions

def is_progress_monotonic(chapters: List[Dict[str, Any]]) -> bool:
    """Check if storyProgress values are monotonically increasing."""
    if not chapters:
        return True

    prev_progress = -1
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue

        progress = chapter.get("storyProgress", 0)
        if not isinstance(progress, (int, float)):
            return False

        if progress <= prev_progress:
            return False

        prev_progress = progress

    return True


def count_progress_violations(chapters: List[Dict[str, Any]]) -> int:
    """Count number of progress violations (non-monotonic)."""
    violations = 0
    prev_progress = -1

    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue

        progress = chapter.get("storyProgress", 0)
        if isinstance(progress, (int, float)):
            if progress <= prev_progress:
                violations += 1
            prev_progress = progress

    return violations


def validate_act_structure(arcs: Dict[str, Any]) -> bool:
    """Validate 4-act structure is correct."""
    if not isinstance(arcs, dict):
        return False

    required_acts = ["act1", "act2a", "act2b", "act3"]
    for act in required_acts:
        if act not in arcs:
            return False

        act_data = arcs[act]
        if not isinstance(act_data, dict):
            return False

        chapters = act_data.get("chapters", [])
        if not isinstance(chapters, list):
            return False

        if len(chapters) != 3:
            return False

    return True


def score_partial_act_structure(arcs: Dict[str, Any]) -> float:
    """Score partial act structure (0.0-1.0)."""
    if not isinstance(arcs, dict):
        return 0.0

    required_acts = ["act1", "act2a", "act2b", "act3"]
    present = sum(1 for act in required_acts if act in arcs)

    return present / len(required_acts)


def calculate_branch_diversity(chapters: List[Dict[str, Any]]) -> float:
    """
    Calculate diversity of choice branches (0.0-1.0).

    Checks if each choice has different consequences.
    """
    if not chapters:
        return 0.0

    diversity_scores = []

    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue

        choices = chapter.get("choices", [])
        if not isinstance(choices, list) or len(choices) < 2:
            continue

        # Extract consequences
        consequences = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            cons = choice.get("consequences", {})
            if isinstance(cons, dict):
                # Simple diversity check: different consequences keys/values
                cons_str = json.dumps(cons, sort_keys=True)
                consequences.append(cons_str)

        # Check uniqueness
        if consequences:
            unique = len(set(consequences))
            diversity = unique / len(consequences)
            diversity_scores.append(diversity)

    if diversity_scores:
        return sum(diversity_scores) / len(diversity_scores)
    else:
        return 0.0


# Export functions
__all__ = [
    "calculate_structure_score",
    "score_blueprint_structure",
    "score_characters_structure",
    "score_story_arc_structure",
    "score_chapters_structure",
    "is_progress_monotonic",
    "validate_act_structure",
    "calculate_branch_diversity"
]
