"""
StoryNet Bittensor Subnet Template Package
==========================================

This package contains the core protocol and utilities for the StoryNet subnet.

Modules:
- protocol: Synapse definitions for communication
- utils: Common utility functions

Example usage:
    >>> from template.protocol import create_blueprint_synapse
    >>> from template.utils import validate_json

    >>> # Create a task
    >>> synapse = create_blueprint_synapse("一个关于太空探险的故事")

    >>> # Validate response
    >>> is_valid, data = validate_json(synapse.output_json)
"""

from .protocol import (
    StoryGenerationSynapse,
    create_blueprint_synapse,
    create_characters_synapse,
    create_story_arc_synapse,
    create_chapters_synapse
)

from .utils import (
    validate_json,
    validate_required_fields,
    stringify,
    compute_hash,
    format_timestamp,
    safe_divide,
    clamp,
    normalize_weights,
    exponential_moving_average,
    get_field_length,
    extract_nested_field,
    Timer,
    chunks
)

__version__ = "1.0.0"

__all__ = [
    # Protocol
    "StoryGenerationSynapse",
    "create_blueprint_synapse",
    "create_characters_synapse",
    "create_story_arc_synapse",
    "create_chapters_synapse",

    # Utils
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
    "chunks",

    # Version
    "__version__"
]
