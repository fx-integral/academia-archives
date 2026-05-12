"""
Lightweight in‑memory model types for optional structured logging / typing.

There is **no database** and **no SQLAlchemy** here anymore.
These classes are plain dataclasses that mirror the old ORM shapes
just enough to keep type hints and any incidental references working.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, Optional


__all__ = ["VoteSnapshot", "LiquiditySnapshot"]


# ──────────────────────────────────────────────────────────────
# Dataclasses (no persistence)
# ──────────────────────────────────────────────────────────────
@dataclass
class VoteSnapshot:
    """
    One snapshot of the full subnet‑weights vector produced by α‑Stake voting.
    Plain data holder – not persisted.
    """
    block_height: int
    voter_hotkey: str
    voter_stake: float
    # JSON dict equivalent: {subnet_id: weight, …}
    weights: Dict[int, float]

    # Timestamp when the snapshot object was created (UTC).
    ts: _dt.datetime = field(default_factory=_dt.datetime.utcnow)

    # Optional compatibility field that used to be the DB primary key.
    # Kept here as Optional to avoid breaking any legacy code paths.
    id: Optional[int] = None


@dataclass
class LiquiditySnapshot:
    """
    Liquidity provided by one miner in one subnet at a given block.
    All values are denominated in **TAO**. Plain data holder – not persisted.
    """
    wallet_hotkey: str
    subnet_id: int
    tao_value: float
    block_height: int

    # Timestamp when the snapshot object was created (UTC).
    ts: _dt.datetime = field(default_factory=_dt.datetime.utcnow)

    # Optional compatibility field that used to be the DB primary key.
    id: Optional[int] = None
