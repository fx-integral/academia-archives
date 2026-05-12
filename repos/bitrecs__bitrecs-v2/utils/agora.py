import os
import httpx
import utils.logger as logger
from datetime import datetime, timezone
from dataclasses import dataclass, field

@dataclass
class AgoraStatus:
    id: str
    from_server: str
    priority: int
    description: str
    status: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


async def post_to_agora(payload: AgoraStatus) -> bool:   
    try:
        url = os.environ.get("AGORA_URL", "")
        key = os.environ.get("AGORA_API_KEY", "")
        headers = {"Content-Type": "application/json", "X-API-Key": key}
        async with httpx.AsyncClient(base_url=url, headers=headers) as client:
            response = await client.post("/submit", json=payload.__dict__)
            response.raise_for_status()
            logger.info(f"Post agora success: {payload}")
            return True
    except Exception as e:
        logger.error(f"Failed to post to Agora: {e}")
        return False