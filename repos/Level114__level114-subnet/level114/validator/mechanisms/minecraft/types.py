"""Minecraft mechanism data structures."""

from dataclasses import dataclass
from typing import Dict


@dataclass
class ScoreCacheEntry:
    score: int
    raw_score: int
    components: Dict[str, float]
    updated_at: float
