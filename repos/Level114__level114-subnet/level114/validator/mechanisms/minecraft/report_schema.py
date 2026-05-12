"""High-level report models building on shared Minecraft report types."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from level114.validator.mechanisms.minecraft.constants import REQUIRED_PLUGINS
from level114.validator.mechanisms.minecraft.report_models import (
    ActivePlayer,
    MemoryInfo,
    SystemInfo,
    parse_active_players,
)


class Payload(BaseModel):
    active_players: List[ActivePlayer] = Field(default_factory=list)
    max_players: int = Field(default=20, ge=1, le=50000)
    memory_ram_info: MemoryInfo = Field(default_factory=MemoryInfo)
    plugins: List[str] = Field(default_factory=list)
    system_info: SystemInfo = Field(default_factory=SystemInfo)
    tps_millis: int = Field(default=50, ge=0, le=25000)
    uptime_ms: int = Field(default=0, ge=0)

    @validator("tps_millis")
    def validate_tps(cls, value: int) -> int:  # noqa: D417
        return value if 0 <= value <= 25000 else 50

    @validator("active_players", pre=True)
    def parse_active_players_field(cls, value: Any) -> List[ActivePlayer]:  # noqa: D417
        return parse_active_players(value)

    @validator("plugins", pre=True)
    def parse_plugins(cls, value: Any) -> List[str]:  # noqa: D417
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        return [str(plugin) for plugin in value if plugin]

    @property
    def tps_actual(self) -> float:
        return 0.0 if self.tps_millis <= 0 else min(self.tps_millis / 1000.0, 20.0)

    @property
    def player_count(self) -> int:
        return len(self.active_players)

    @property
    def player_ratio(self) -> float:
        return 0.0 if self.max_players <= 0 else min(self.player_count / self.max_players, 1.0)

    @property
    def has_required_plugins(self) -> bool:
        if not REQUIRED_PLUGINS:
            return True
        plugin_set = {
            plugin.strip().lower()
            for plugin in self.plugins
            if isinstance(plugin, str) and plugin.strip()
        }
        required = {plugin.strip().lower() for plugin in REQUIRED_PLUGINS if plugin}
        return required.issubset(plugin_set)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Payload":
        if not data:
            return cls()
        return cls(
            active_players=data.get("active_players", []),
            max_players=data.get("max_players", 20),
            memory_ram_info=MemoryInfo.from_dict(data.get("memory_ram_info")),
            plugins=data.get("plugins", []),
            system_info=SystemInfo.from_dict(data.get("system_info")),
            tps_millis=data.get("tps_millis", 50),
            uptime_ms=data.get("uptime_ms", 0),
        )


class ServerReport(BaseModel):
    id: str = Field(default="")
    server_id: str = Field(default="")
    counter: int = Field(default=0, ge=0)
    client_timestamp_ms: int = Field(default=0, ge=0)
    nonce: str = Field(default="")
    plugin_hash: str = Field(default="")
    payload_hash: str = Field(default="")
    payload: Payload = Field(default_factory=Payload)
    signature: str = Field(default="")
    created_at: str = Field(default="")

    @validator("client_timestamp_ms")
    def validate_timestamp(cls, value: int) -> int:  # noqa: D417
        import time

        current_ms = int(time.time() * 1000)
        return value if abs(value - current_ms) <= 24 * 60 * 60 * 1000 else current_ms

    @validator("created_at")
    def validate_created_at(cls, value: str) -> str:  # noqa: D417
        if not value:
            return datetime.now().isoformat() + "Z"
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value
        except (ValueError, AttributeError):
            return datetime.now().isoformat() + "Z"

    @property
    def age_seconds(self) -> float:
        try:
            import time

            current_ms = int(time.time() * 1000)
            return (current_ms - self.client_timestamp_ms) / 1000.0
        except Exception:  # noqa: BLE001
            return 0.0

    @property
    def is_fresh(self) -> bool:
        return self.age_seconds < 300

    def to_canonical_dict(self) -> Dict[str, Any]:
        payload_dict = self.payload.model_dump()
        return {
            "active_players": sorted(
                [
                    {"name": p.name, "uuid": p.uuid, "power": p.power}
                    for p in self.payload.active_players
                ],
                key=lambda item: item["uuid"],
            ),
            "max_players": payload_dict["max_players"],
            "memory_ram_info": payload_dict["memory_ram_info"],
            "plugins": sorted(payload_dict["plugins"]),
            "system_info": payload_dict["system_info"],
            "tps_millis": payload_dict["tps_millis"],
            "uptime_ms": payload_dict["uptime_ms"],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ServerReport":
        if not data:
            return cls()
        return cls(
            id=str(data.get("id", "")),
            server_id=str(data.get("server_id", "")),
            counter=data.get("counter", 0),
            client_timestamp_ms=data.get("client_timestamp_ms", 0),
            nonce=str(data.get("nonce", "")),
            plugin_hash=str(data.get("plugin_hash", "")),
            payload_hash=str(data.get("payload_hash", "")),
            payload=Payload.from_dict(data.get("payload")),
            signature=str(data.get("signature", "")),
            created_at=str(data.get("created_at", "")),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ServerReport":
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, Exception):  # noqa: BLE001
            return cls()
