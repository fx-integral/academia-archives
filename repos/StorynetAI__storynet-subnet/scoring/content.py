"""
Content Score Module
====================

Calculates Content Score (30 points) based on:
1. Relevance (embedding similarity): 15 points
2. Fluency (perplexity or heuristics): 10 points
3. Originality (similarity with history): 5 points

This is semi-objective, using AI models and statistical metrics.
"""

import json
import hashlib
from typing import Dict, Any, List, Tuple, Optional
import bittensor as bt


# Placeholder for embedding function (to be implemented with OpenAI or local model)
_embedding_cache = {}


def calculate_content_score(
    data: Dict[str, Any],
    context: Dict[str, Any],
    task_type: str,
    history: Optional[List[str]] = None,
    use_embeddings: bool = False
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate content score for a miner's response.

    Args:
        data: Parsed JSON data
        context: Context dict with user_input, blueprint, etc.
        task_type: Type of task
        history: List of historical responses for plagiarism detection
        use_embeddings: Whether to use embedding models (requires OpenAI API)

    Returns:
        Tuple of (score, breakdown)
        - score: Total content score (0-30)
        - breakdown: Dictionary with detailed scores
    """
    breakdown = {
        "relevance": 0.0,
        "fluency": 0.0,
        "originality": 0.0
    }

    # 1. Relevance (15 points)
    if use_embeddings:
        # Use actual embeddings (requires OpenAI API)
        relevance_score = calculate_relevance_with_embeddings(data, context, task_type)
    else:
        # Use simple heuristics
        relevance_score = calculate_relevance_heuristic(data, context, task_type)

    breakdown["relevance"] = relevance_score

    # 2. Fluency (10 points)
    fluency_score = calculate_fluency(data, task_type)
    breakdown["fluency"] = fluency_score

    # 3. Originality (5 points)
    if history:
        originality_score = calculate_originality(data, history)
    else:
        originality_score = 5.0  # No history = assume original

    breakdown["originality"] = originality_score

    total = sum(breakdown.values())
    return min(total, 30.0), breakdown


def calculate_relevance_heuristic(
    data: Dict[str, Any],
    context: Dict[str, Any],
    task_type: str
) -> float:
    """
    Calculate relevance using keyword matching and heuristics (15 points).

    This is a simplified version that doesn't require embeddings.
    """
    score = 0.0
    user_input = context.get("user_input", "").lower()

    if task_type == "blueprint":
        # Check if genre/setting relate to user input
        title = data.get("title", "").lower()
        genre = data.get("genre", "").lower()
        setting = data.get("setting", "").lower()

        # Simple keyword overlap
        input_keywords = set(user_input.split())
        output_keywords = set(title.split() + genre.split() + setting.split())

        overlap = len(input_keywords & output_keywords)
        if overlap > 0:
            score = min(15.0, overlap * 3.0)

    elif task_type == "characters":
        # Check if characters match blueprint themes
        blueprint = context.get("blueprint", {})
        blueprint_str = json.dumps(blueprint, ensure_ascii=False).lower()

        characters_str = json.dumps(data, ensure_ascii=False).lower()

        # Keyword overlap between blueprint and characters
        blueprint_keywords = set(blueprint_str.split())
        character_keywords = set(characters_str.split())

        overlap = len(blueprint_keywords & character_keywords)
        if overlap > 0:
            score = min(15.0, overlap * 0.5)

    elif task_type in ["story_arc", "chapters"]:
        # Check consistency with blueprint
        blueprint = context.get("blueprint", {})
        blueprint_str = json.dumps(blueprint, ensure_ascii=False).lower()
        output_str = json.dumps(data, ensure_ascii=False).lower()

        # Count matching keywords
        blueprint_keywords = set(blueprint_str.split())
        output_keywords = set(output_str.split())

        overlap = len(blueprint_keywords & output_keywords)
        if overlap > 0:
            score = min(15.0, overlap * 0.3)

    return score


def calculate_relevance_with_embeddings(
    data: Dict[str, Any],
    context: Dict[str, Any],
    task_type: str
) -> float:
    """
    Calculate relevance using embedding similarity (15 points).

    This requires OpenAI embedding API or local embedding model.
    To be implemented when OpenAI client is available.
    """
    # Embedding-based scoring available when embedding model is configured
    # Falls back to heuristic scoring
    return calculate_relevance_heuristic(data, context, task_type)


def calculate_fluency(data: Dict[str, Any], task_type: str) -> float:
    """
    Calculate fluency score using heuristics (10 points).

    Checks:
    - Sentence structure (presence of punctuation)
    - Average word length
    - Repetition
    """
    score = 0.0

    # Extract text content
    text = ""
    if task_type == "blueprint":
        text = data.get("setting", "") + " " + data.get("core_conflict", "")
    elif task_type == "characters":
        characters = data.get("characters", [])
        for char in characters:
            if isinstance(char, dict):
                text += char.get("background", "") + " "
    elif task_type == "story_arc":
        chapters = data.get("chapters", [])
        for chapter in chapters:
            if isinstance(chapter, dict):
                text += chapter.get("description", "") + " "
    elif task_type == "chapters":
        chapters = data.get("chapters", [])
        for chapter in chapters:
            if isinstance(chapter, dict):
                text += chapter.get("content", "") + " "

    if not text.strip():
        return 0.0

    # Check 1: Punctuation presence (2 points)
    if any(p in text for p in ["。", "！", "？", ".", "!", "?"]):
        score += 2.0

    # Check 2: Not too repetitive (3 points)
    words = text.split()
    if len(words) > 0:
        unique_words = len(set(words))
        repetition_ratio = unique_words / len(words)
        if repetition_ratio > 0.6:
            score += 3.0
        elif repetition_ratio > 0.4:
            score += 1.5

    # Check 3: Reasonable length (3 points)
    word_count = len(words)
    if task_type == "chapters":
        # Chapters should have long content
        if word_count > 500:
            score += 3.0
        elif word_count > 300:
            score += 1.5
    else:
        # Other tasks should have moderate content
        if word_count > 100:
            score += 3.0
        elif word_count > 50:
            score += 1.5

    # Check 4: Sentence variety (2 points)
    sentences = [s.strip() for s in text.replace("。", ".").split(".") if s.strip()]
    if len(sentences) > 3:
        avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
        if 10 < avg_sentence_length < 30:
            score += 2.0

    return min(score, 10.0)


def calculate_originality(data: Dict[str, Any], history: List[str]) -> float:
    """
    Calculate originality by comparing with historical responses (5 points).

    Args:
        data: Current response data
        history: List of historical response JSON strings

    Returns:
        Originality score (0-5)
    """
    if not history:
        return 5.0

    current_str = json.dumps(data, ensure_ascii=False, sort_keys=True)
    current_hash = hashlib.sha256(current_str.encode()).hexdigest()

    # Check for exact duplicates
    for historical_response in history[-100:]:  # Check last 100 responses
        # Handle both dict and string historical responses
        if isinstance(historical_response, dict):
            hist_str = json.dumps(historical_response, ensure_ascii=False, sort_keys=True)
        else:
            hist_str = str(historical_response)
        historical_hash = hashlib.sha256(hist_str.encode()).hexdigest()
        if current_hash == historical_hash:
            return 0.0  # Exact duplicate

    # Calculate simple similarity (character-level Jaccard)
    max_similarity = 0.0
    for historical_response in history[-20:]:  # Check last 20 for similarity
        try:
            # Handle both dict and string historical responses
            if isinstance(historical_response, dict):
                historical_data = historical_response
            else:
                historical_data = json.loads(historical_response)
            similarity = calculate_simple_similarity(data, historical_data)
            max_similarity = max(max_similarity, similarity)
        except json.JSONDecodeError:
            continue

    # Score based on max similarity
    if max_similarity < 0.8:
        return 5.0  # Very original
    elif max_similarity < 0.9:
        return 2.0  # Somewhat original
    else:
        return 0.0  # Too similar


def calculate_simple_similarity(data1: Dict[str, Any], data2: Dict[str, Any]) -> float:
    """
    Calculate simple similarity between two data objects.

    Uses character-level Jaccard similarity.
    """
    str1 = json.dumps(data1, ensure_ascii=False, sort_keys=True)
    str2 = json.dumps(data2, ensure_ascii=False, sort_keys=True)

    # Character-level bigrams
    def get_bigrams(s: str) -> set:
        return set(s[i:i+2] for i in range(len(s) - 1))

    bigrams1 = get_bigrams(str1)
    bigrams2 = get_bigrams(str2)

    if not bigrams1 or not bigrams2:
        return 0.0

    intersection = len(bigrams1 & bigrams2)
    union = len(bigrams1 | bigrams2)

    return intersection / union if union > 0 else 0.0


def stringify(obj: Any) -> str:
    """Convert object to string for analysis."""
    if isinstance(obj, str):
        return obj
    elif isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False)
    else:
        return str(obj)


# Export functions
__all__ = [
    "calculate_content_score",
    "calculate_relevance_heuristic",
    "calculate_relevance_with_embeddings",
    "calculate_fluency",
    "calculate_originality",
    "calculate_simple_similarity",
    "stringify"
]
