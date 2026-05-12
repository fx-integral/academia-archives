from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

UNUSUAL_WHALES_COST_PER_CALL = Decimal("0.0001")


class NewsHeadline(BaseModel):
    headline: str
    source: str
    created_at: str
    is_major: bool = False
    sentiment: str | None = None
    tickers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class NewsHeadlinesResponse(BaseModel):
    headlines: list[NewsHeadline]

    model_config = ConfigDict(extra="allow")


def calculate_cost() -> Decimal:
    return UNUSUAL_WHALES_COST_PER_CALL
