# The MIT License (MIT)
# Copyright © 2026 UnitOne Labs

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GatewayError:
    """Gateway API error response."""
    error: str
    message: str
    status: int


class GatewayAPIError(Exception):
    """Exception raised when gateway API returns an error."""
    def __init__(self, error: GatewayError):
        self.error = error
        super().__init__(f"{error.error}: {error.message} (status: {error.status})")


@dataclass
class Node:
    """Node information from gateway."""
    id: str
    region: str


@dataclass
class CheckStats:
    """Statistics for a specific check type (health, data, benchmark)."""
    total: int
    passed: int

    def success_rate(self) -> float:
        """Calculate success rate as a value between 0 and 1."""
        if self.total == 0:
            return 0.0
        return self.passed / self.total


@dataclass
class NodeStatistics:
    """Statistics for a single node."""
    node_id: str
    health: CheckStats
    data: CheckStats
    benchmark: CheckStats


@dataclass
class MinerNode:
    """Miner node with health statistics."""
    miner_hotkey: str
    node_id: str
    region: str
    health: CheckStats
    data_verified: bool = True
    avg_latency_ms: Optional[float] = None


@dataclass
class ReferenceBlock:
    """Reference block for verification."""
    block_number: int
    block_hash: str
    verification_type: str
    events_data_size: int
    events_hash: str


@dataclass
class RegionStats:
    """Statistics for a region."""
    success: bool
    count: int
    latency: int
    error: Optional[str] = None


@dataclass
class StatisticsMeta:
    """Metadata for statistics response."""
    total_nodes: int
    regions: Dict[str, RegionStats]
    total_latency_ms: int


@dataclass
class StatisticsResponse:
    """Full statistics response."""
    statistics: List[NodeStatistics]
    meta: StatisticsMeta


@dataclass
class LatencyStats:
    """Latency statistics."""
    min_ms: float
    max_ms: float
    avg_ms: float

    @classmethod
    def from_latencies(cls, latencies: List[float]) -> Optional["LatencyStats"]:
        """Create from list of latency values."""
        if not latencies:
            return None
        return cls(
            min_ms=min(latencies),
            max_ms=max(latencies),
            avg_ms=sum(latencies) / len(latencies),
        )


@dataclass
class RPCError:
    """JSON-RPC error."""
    code: int
    message: str


@dataclass
class RPCResponse:
    """JSON-RPC response from gateway."""
    jsonrpc: str
    id: int
    result: Optional[Any] = None
    error: Optional[RPCError] = None
    latency_ms: Optional[int] = None

    def is_error(self) -> bool:
        """Check if the response is an error."""
        return self.error is not None
