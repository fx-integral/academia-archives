"""Data structures and constants for TCL mechanism."""

from dataclasses import dataclass
from typing import Dict

MAX_VALUES = {
    "online_players": 5.0,
    "avg_playtime_minutes": 30.0,
    "daily_unique_logins": 150.0,
    "monthly_new_users": 600.0,
}

COMPONENT_WEIGHTS = {
    "online_players": 0.20,
    "avg_playtime_minutes": 0.30,
    "daily_unique_logins": 0.20,
    "monthly_new_users": 0.30,
}


@dataclass
class TclScoreEntry:
    score: int
    score_fraction: float
    components: Dict[str, Dict[str, float]]
    metrics: Dict[str, float]
    updated_at: float
