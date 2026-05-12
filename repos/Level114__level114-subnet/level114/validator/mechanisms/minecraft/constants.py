"""Constants and helpers for Minecraft validator scoring."""

from __future__ import annotations

import os
from typing import Dict, Set

# Performance targets
IDEAL_TPS = 20.0
MIN_TPS_THRESHOLD = 5.0
MAX_TPS_BONUS = 20.0

# Player activity
MAX_PLAYERS_WEIGHT = 200
MIN_PLAYERS_FOR_BONUS = 5
OPTIMAL_PLAYER_RATIO_MIN = 0.2
OPTIMAL_PLAYER_RATIO_MAX = 0.8

# Plugins
REQUIRED_PLUGINS: Set[str] = {"Level114", "LuckPerms", "CraftingStore", "PlayerPoints" }
BONUS_PLUGINS: Set[str] = {"ViaVersion", "ViaBackwards", "ViaRewind"}

# Primary weights (sum to 1.0)
W_INFRA = 0.20
W_PART = 0.20
W_RELY = 0.60

# Sub-component weights
W_INFRA_TPS = 1.0
W_PART_COMPLIANCE = 0.8571428571428571
W_PART_PLAYERS = 0.14285714285714285
W_RELY_PLAYER_POWER = 0.90
W_RELY_STABILITY = 0.05
W_RELY_RECOVERY = 0.05

# Score range
MIN_SCORE = 0
MAX_SCORE = 1000
DEFAULT_SCORE = 100

# Smoothing
EMA_ALPHA = 0.2
MIN_SCORE_CHANGE = 1
MAX_SCORE_CHANGE = 200

# Classification thresholds
EXCELLENT_SCORE_THRESHOLD = 850
GOOD_SCORE_THRESHOLD = 650
POOR_SCORE_THRESHOLD = 300

# History sampling
MAX_REPORT_HISTORY = 60
MIN_REPORTS_FOR_RELIABILITY = 5
TPS_STABILITY_WINDOW = 20
MAX_TPS_COEFFICIENT_OF_VARIATION = 0.3
RECOVERY_TPS_THRESHOLD = 18.0
RECOVERY_SAMPLE_COUNT = 10
MAX_RECOVERY_TIME_MINUTES = 30

# Environment overrides
IDEAL_TPS = float(os.getenv("LEVEL114_IDEAL_TPS", IDEAL_TPS))
MAX_PLAYERS_WEIGHT = int(os.getenv("LEVEL114_MAX_PLAYERS_WEIGHT", MAX_PLAYERS_WEIGHT))
W_INFRA = float(os.getenv("LEVEL114_W_INFRA", W_INFRA))
W_PART = float(os.getenv("LEVEL114_W_PART", W_PART))
W_RELY = float(os.getenv("LEVEL114_W_RELY", W_RELY))
W_RELY_PLAYER_POWER = float(
    os.getenv("LEVEL114_W_RELY_PLAYER_POWER", W_RELY_PLAYER_POWER)
)
W_RELY_STABILITY = float(os.getenv("LEVEL114_W_RELY_STABILITY", W_RELY_STABILITY))
W_RELY_RECOVERY = float(os.getenv("LEVEL114_W_RELY_RECOVERY", W_RELY_RECOVERY))
EMA_ALPHA = float(os.getenv("LEVEL114_EMA_ALPHA", EMA_ALPHA))
MAX_SCORE = int(os.getenv("LEVEL114_MAX_SCORE", MAX_SCORE))
DEBUG_SCORING = os.getenv("LEVEL114_DEBUG_SCORING", "false").lower() == "true"


def validate_constants() -> None:
    """Ensure weight distribution and boundaries remain valid."""
    total_weight = W_INFRA + W_PART + W_RELY
    if abs(total_weight - 1.0) > 0.001:
        raise ValueError(f"Primary weights must sum to 1.0, got {total_weight}")

    if abs(W_INFRA_TPS - 1.0) > 0.001:
        raise ValueError(f"Infrastructure weights must sum to 1.0, got {W_INFRA_TPS}")

    part_total = W_PART_COMPLIANCE + W_PART_PLAYERS
    if abs(part_total - 1.0) > 0.001:
        raise ValueError(f"Participation weights must sum to 1.0, got {part_total}")

    rely_total = W_RELY_PLAYER_POWER + W_RELY_STABILITY + W_RELY_RECOVERY
    if abs(rely_total - 1.0) > 0.001:
        raise ValueError(f"Reliability weights must sum to 1.0, got {rely_total}")

    if not (0 < IDEAL_TPS <= 30):
        raise ValueError(f"IDEAL_TPS must be in (0, 30], got {IDEAL_TPS}")

    if not (0 < EMA_ALPHA <= 1):
        raise ValueError(f"EMA_ALPHA must be in (0, 1], got {EMA_ALPHA}")

    if MAX_SCORE <= MIN_SCORE:
        raise ValueError(f"MAX_SCORE ({MAX_SCORE}) must be > MIN_SCORE ({MIN_SCORE})")


def get_score_classification(score: int) -> str:
    if score >= EXCELLENT_SCORE_THRESHOLD:
        return "excellent"
    if score >= GOOD_SCORE_THRESHOLD:
        return "good"
    if score >= POOR_SCORE_THRESHOLD:
        return "average"
    return "poor"


def get_constants_summary() -> Dict[str, object]:
    return {
        "performance_targets": {
            "ideal_tps": IDEAL_TPS,
            "max_players_weight": MAX_PLAYERS_WEIGHT,
        },
        "weights": {"infrastructure": W_INFRA, "participation": W_PART, "reliability": W_RELY},
        "sub_weights": {
            "infra": {"tps": W_INFRA_TPS},
            "part": {"compliance": W_PART_COMPLIANCE, "players": W_PART_PLAYERS},
            "rely": {
                "player_power": W_RELY_PLAYER_POWER,
                "stability": W_RELY_STABILITY,
                "recovery": W_RELY_RECOVERY,
            },
        },
        "score_range": {
            "min": MIN_SCORE,
            "max": MAX_SCORE,
            "thresholds": {
                "excellent": EXCELLENT_SCORE_THRESHOLD,
                "good": GOOD_SCORE_THRESHOLD,
                "poor": POOR_SCORE_THRESHOLD,
            },
        },
        "required_plugins": sorted(REQUIRED_PLUGINS),
        "bonus_plugins": sorted(BONUS_PLUGINS),
    }


if __name__ != "__main__":
    validate_constants()
