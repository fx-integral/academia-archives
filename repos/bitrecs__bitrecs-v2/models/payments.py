from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field

class AgentUploadResponse(BaseModel):
    """Response model for successful agent upload"""
    status: str = Field(..., description="Status of the upload operation")
    message: str = Field(..., description="Detailed message about the upload result")

class ErrorResponse(BaseModel):
    """Error response model"""
    detail: str = Field(..., description="Error message describing what went wrong")
    

class Payment(BaseModel):
    payment_block_hash: str
    payment_extrinsic_index: str
    agent_id: UUID
    miner_hotkey: str
    miner_coldkey: str
    amount_rao: int
    created_at: datetime


class UploadPriceResponse(BaseModel):
    """Response model for successful agent upload"""
    amount_rao: int = Field(..., description="Amount to send for evaluation (in RAO)")
    bitrecs_price_usd: float = Field(..., description="Current price of Bitrecs in USD")    