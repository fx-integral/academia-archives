from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class InferenceReport(BaseModel):
    evaluation_run_id: UUID
    provider: str
    model: str
    temperature: float
    messages: List[Dict[str, Any]]
    status_code: Optional[int] = None
    response: Optional[str] = None
    num_input_tokens: Optional[int] = None
    num_output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    response_sent_at: Optional[datetime] = None
    request_received_at: Optional[datetime] = None