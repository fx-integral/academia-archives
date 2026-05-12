from dataclasses import dataclass
from typing import Optional, List


@dataclass
class MemoryInfo:
    free_memory_bytes: Optional[int] = None
    total_memory_bytes: Optional[int] = None
    used_memory_bytes: Optional[int] = None


@dataclass
class SystemInfo:
    cpu_cores: Optional[int] = None
    cpu_model: Optional[str] = None
    cpu_threads: Optional[int] = None
    java_version: Optional[str] = None
    memory_ram_info: Optional[MemoryInfo] = None
    os_arch: Optional[str] = None
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    uptime_ms: Optional[int] = None


@dataclass
class ReportPayload:
    active_players: Optional[List[str]] = None
    max_players: Optional[int] = None
    memory_ram_info: Optional[MemoryInfo] = None
    plugins: Optional[List[str]] = None
    system_info: Optional[SystemInfo] = None
    tps_millis: Optional[int] = None
    uptime_ms: Optional[int] = None


@dataclass
class ServerReport:
    id: str
    server_id: str
    counter: int
    client_timestamp_ms: int
    nonce: str
    plugin_hash: str
    payload_hash: str
    payload: Optional[ReportPayload]
    signature: str
    created_at: str


