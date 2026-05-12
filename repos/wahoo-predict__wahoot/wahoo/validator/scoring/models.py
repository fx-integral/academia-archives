from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PerformanceMetrics(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    total_volume_usd: Optional[float] = Field(default=None, alias="total_volume_usd")
    weighted_volume: Optional[float] = Field(default=None, alias="weighted_volume")
    profit: Optional[float] = Field(default=None, alias="profit")
    trade_count: Optional[int] = Field(default=None, alias="trade_count")
    realized_profit_usd: Optional[float] = Field(
        default=None, alias="realized_profit_usd"
    )
    unrealized_profit_usd: Optional[float] = Field(
        default=None, alias="unrealized_profit_usd"
    )
    win_rate: Optional[float] = Field(default=None, alias="win_rate")
    total_fees_paid_usd: Optional[float] = Field(
        default=None, alias="total_fees_paid_usd"
    )
    open_positions_count: Optional[int] = Field(
        default=None, alias="open_positions_count"
    )
    last_active_timestamp: Optional[str] = Field(
        default=None, alias="last_active_timestamp"
    )
    referral_count: Optional[int] = Field(default=None, alias="referral_count")
    referral_volume_usd: Optional[float] = Field(
        default=None, alias="referral_volume_usd"
    )

    _float_fields = (
        "total_volume_usd",
        "weighted_volume",
        "profit",
        "realized_profit_usd",
        "unrealized_profit_usd",
        "win_rate",
        "total_fees_paid_usd",
        "referral_volume_usd",
    )
    _int_fields = ("trade_count", "open_positions_count", "referral_count")

    @field_validator(*_float_fields, mode="before")
    @classmethod
    def _ensure_float(cls, value):
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError("Expected a numeric value")

    @field_validator(*_int_fields, mode="before")
    @classmethod
    def _ensure_int(cls, value):
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError("Expected an integer value")


class ValidationRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    hotkey: str
    signature: Optional[str] = None
    message: Optional[str] = None
    performance: PerformanceMetrics = Field(default_factory=PerformanceMetrics)
    wahoo_user_id: Optional[str] = Field(default=None, alias="userId")

    @field_validator("hotkey")
    @classmethod
    def _normalize_hotkey(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("hotkey cannot be empty")
        return normalized
