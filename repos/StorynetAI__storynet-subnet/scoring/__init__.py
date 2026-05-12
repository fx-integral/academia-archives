"""
StoryNet Scoring Package
=======================

Contains scoring modules for evaluating miner responses.

Modules:
- technical: Technical score (JSON validity, schema, response time) - 20 points
- structure: Structure score (story arc, character relationships) - 30 points
- content: Content score (relevance, fluency, originality) - 20 points
- narrative: Narrative merit score (AI-based quality evaluation) - 30 points

Total Score = Technical (20) + Structure (30) + Content (20) + Narrative (30) = 100

Note: Narrative scoring uses server-side AI evaluation with private prompts.
Config location: ~/.storynet/narrative_config.yaml
"""

from .technical import (
    calculate_technical_score,
    validate_json_structure
)

from .structure import (
    calculate_structure_score,
    is_progress_monotonic,
    validate_act_structure
)

from .content import (
    calculate_content_score,
    calculate_originality
)

from .narrative import (
    calculate_narrative_score,
    NarrativeEvaluator,
    get_evaluator
)

__all__ = [
    # Technical
    "calculate_technical_score",
    "validate_json_structure",

    # Structure
    "calculate_structure_score",
    "is_progress_monotonic",
    "validate_act_structure",

    # Content
    "calculate_content_score",
    "calculate_originality",

    # Narrative (AI-based)
    "calculate_narrative_score",
    "NarrativeEvaluator",
    "get_evaluator"
]
