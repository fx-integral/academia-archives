from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class ModelInfoRequest(BaseModel):
    request_type: str = "model_info"

class InferenceRequest(BaseModel):
    request_type: str = "inference"
    model: str
    messages: List[Dict[str, Any]]
    max_tokens: int = 131072
    temperature: float = 0.7
    trace_id: str
