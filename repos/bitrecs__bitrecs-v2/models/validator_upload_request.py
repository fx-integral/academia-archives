from typing import Any, Dict
from dataclasses import asdict, dataclass

@dataclass
class ValidatorUploadRequest:
    created_at: str
    hotkey: str
    uid: int   

    def to_dict(self) -> Dict[str, Any]:        
        return asdict(self)