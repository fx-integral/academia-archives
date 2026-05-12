from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidatorServer:
    id: str
    hotkey: str
    registered_at: Optional[str] = None


