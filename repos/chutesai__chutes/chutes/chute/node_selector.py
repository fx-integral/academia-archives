"""
Node selection filtering.
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class NodeSelector(BaseModel):
    gpu_count: int = Field(1, ge=1, le=8)
    min_vram_gb_per_gpu: int = Field(16, ge=16, le=140)
    max_hourly_price_per_gpu: Optional[float] = Field(None, gt=0, lt=10)
    include: Optional[List[str]] = None
    exclude: Optional[List[str]] = None
