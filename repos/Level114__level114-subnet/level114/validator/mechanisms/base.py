"""Base definitions for validator mechanisms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class MechanismContext:
    """Shared context passed to validator mechanisms."""

    config: Any
    subtensor: Any
    metagraph: Any
    wallet: Any
    collector_api: Any


class ValidatorMechanism:
    """Base class for validator mechanisms."""

    mechanism_id: int = -1
    mechanism_name: str = "base"

    def __init__(self, context: MechanismContext) -> None:
        self.context = context
        self.cycle_count: int = 0

    async def run_cycle(self) -> Dict[str, Any]:
        """Run a single mechanism cycle."""
        raise NotImplementedError

    def get_status(self) -> Dict[str, Any]:
        """Return mechanism specific status information."""
        return {
            "cycle_count": self.cycle_count,
            "mechanism_id": self.mechanism_id,
            "mechanism_name": self.mechanism_name,
        }

    def get_server_id_for_hotkey(self, hotkey: str) -> Optional[str]:
        """Optional helper for cached server id lookup."""
        return None

    def get_cached_score(self, server_id: str) -> Optional[Any]:
        """Optional helper for cached score lookup."""
        return None

    async def apply_weights(self, cycle_stats: Dict[str, Any]) -> bool:
        """Apply weights for the given cycle if needed."""
        return False
