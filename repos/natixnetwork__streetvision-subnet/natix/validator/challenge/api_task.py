from io import BytesIO

import bittensor as bt
from httpx import AsyncClient, HTTPStatusError, Timeout
from PIL import Image

from natix.validator.api_client import build_auth_headers


async def fetch_api_challenge(validator, label: int) -> dict | None:
    """Fetch a benchmark challenge image from the proxy API and download it from S3."""
    try:
        headers = build_auth_headers(validator.wallet)
        body = {"scoring_method": 0, "category": 0, "label": int(label)}
        async with AsyncClient(timeout=Timeout(30)) as client:
            response = await client.post(
                f"{validator.config.proxy.proxy_client_url}/tasks/request",
                headers=headers,
                json=body,
            )
        if response.status_code == 404:
            bt.logging.warning("[API] No benchmark tasks available")
            return None
        if response.status_code == 429:
            bt.logging.warning("[API] Rate limited on /tasks/request")
            return None
        response.raise_for_status()
        task = response.json()
    except HTTPStatusError as e:
        bt.logging.warning(f"[API] Task request failed: {e.response.status_code}")
        return None
    except Exception as e:
        bt.logging.error(f"[API] Task request error: {e}")
        return None

    try:
        async with AsyncClient(timeout=Timeout(30)) as client:
            img_response = await client.get(task["s3_url"])
            img_response.raise_for_status()
        image = Image.open(BytesIO(img_response.content)).convert("RGB")
    except Exception as e:
        bt.logging.error(f"[API] Failed to download task image: {e}")
        return None

    return {"image": image, "label": int(task["label"]), "task_id": task["task_id"]}
