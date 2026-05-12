"""Reusable Pydantic models shared by Minecraft report parsing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class MemoryInfo(BaseModel):
    free_bytes: int = Field(default=0, ge=0)
    used_bytes: int = Field(default=0, ge=0)
    total_bytes: int = Field(default=0, ge=0)

    @validator("total_bytes")
    def validate_total_bytes(cls, value: int, values: Dict[str, Any]) -> int:  # noqa: D417
        used = values.get("used_bytes", 0)
        free = values.get("free_bytes", 0)
        expected = used + free
        if expected > 0 and abs(value - expected) / expected > 0.05:
            return expected
        return max(value, 0)

    @property
    def usage_ratio(self) -> float:
        return 0.0 if self.total_bytes <= 0 else min(self.used_bytes / self.total_bytes, 1.0)

    @property
    def free_ratio(self) -> float:
        return 0.0 if self.total_bytes <= 0 else min(self.free_bytes / self.total_bytes, 1.0)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MemoryInfo":
        if not data:
            return cls()
        return cls(
            free_bytes=data.get("free_memory_bytes", 0),
            used_bytes=data.get("used_memory_bytes", 0),
            total_bytes=data.get("total_memory_bytes", 0),
        )


class SystemInfo(BaseModel):
    cpu_cores: int = Field(default=1, ge=1, le=256)
    cpu_threads: int = Field(default=1, ge=1, le=512)
    cpu_model: str = Field(default="Unknown CPU")
    java_version: str = Field(default="Unknown")
    os_name: str = Field(default="Unknown")
    os_version: str = Field(default="Unknown")
    os_arch: str = Field(default="Unknown")
    uptime_ms: int = Field(default=0, ge=0)
    memory_ram_info: MemoryInfo = Field(default_factory=MemoryInfo)

    @validator("uptime_ms")
    def validate_uptime(cls, value: int) -> int:  # noqa: D417
        return min(value, 100 * 365 * 24 * 60 * 60 * 1000)

    @property
    def uptime_hours(self) -> float:
        return self.uptime_ms / (1000 * 60 * 60)

    @property
    def uptime_days(self) -> float:
        return self.uptime_hours / 24

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SystemInfo":
        if not data:
            return cls()
        return cls(
            cpu_cores=data.get("cpu_cores", 1),
            cpu_threads=data.get("cpu_threads", 1),
            cpu_model=data.get("cpu_model", "Unknown CPU"),
            java_version=data.get("java_version", "Unknown"),
            os_name=data.get("os_name", "Unknown"),
            os_version=data.get("os_version", "Unknown"),
            os_arch=data.get("os_arch", "Unknown"),
            uptime_ms=data.get("uptime_ms", 0),
            memory_ram_info=MemoryInfo.from_dict(data.get("memory_ram_info")),
        )


class ActivePlayer(BaseModel):
    name: str = Field(default="Unknown")
    uuid: str = Field(default="00000000-0000-0000-0000-000000000000")
    power: float = Field(default=0.0, ge=0.0)

    @validator("uuid")
    def validate_uuid(cls, value: str) -> str:  # noqa: D417
        if len(value) != 36 or value.count("-") != 4:
            return "00000000-0000-0000-0000-000000000000"
        return value

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ActivePlayer":
        if not data:
            return cls()
        power_value = data.get("power", 0.0)
        try:
            power = float(power_value)
        except (TypeError, ValueError):
            power = 0.0
        return cls(
            name=str(data.get("name", "Unknown")),
            uuid=str(data.get("uuid", "00000000-0000-0000-0000-000000000000")),
            power=max(power, 0.0),
        )


def parse_active_players(raw: Optional[List[Any]]) -> List[ActivePlayer]:
    if not raw:
        return []
    players: List[ActivePlayer] = []
    for item in raw:
        if isinstance(item, str):
            players.append(ActivePlayer(name=item))
        elif isinstance(item, dict):
            players.append(ActivePlayer.from_dict(item))
    return players
