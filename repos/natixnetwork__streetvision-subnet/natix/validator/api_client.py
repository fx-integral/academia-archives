import time
import hashlib
from typing import List

import bittensor as bt
from httpx import Client, HTTPStatusError, ReadTimeout, Timeout


def build_auth_headers(wallet) -> dict:
    timestamp = str(int(time.time()))
    signature = wallet.hotkey.sign(timestamp.encode()).hex()
    return {
        "x-hotkey": wallet.hotkey.ss58_address,
        "x-signature": signature,
        "x-timestamp": timestamp,
    }


def statistics_assign_task(
    validator,
    miner_uid_list: List[int],
    scoring_method: int,
    category: int,
    label: int,
    image: str,
    task_id: str | None = None,
) -> dict | None:
    try:
        clean_image = str(image).strip()
        encoded_image = clean_image.encode()
        payload_ref = hashlib.sha256(encoded_image).hexdigest()
        payload = {
            "validator_uid": int(validator.uid),
            "miner_uid_list": [int(uid) for uid in miner_uid_list],
            "scoring_method": scoring_method,
            "category": category,
            "label": int(label),
            "payload_ref": str(payload_ref),
        }
        if task_id is not None:
            payload["task_id"] = str(task_id)
        with Client(timeout=Timeout(30)) as client:
            response = client.post(
                f"{validator.config.proxy.proxy_client_url}/tasks/statistics/assign",
                json=payload,
            )
        response.raise_for_status()
        bt.logging.info("Successfully reported task assignment to /statistics/assign")
        return response.json()
    except ReadTimeout:
        bt.logging.warning("Statistics assignment request timed out")
        return None
    except HTTPStatusError as e:
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text
        bt.logging.warning(f"Statistics assignment request failed: {error_detail}")
        return None
    except Exception as e:
        bt.logging.exception(f"Unexpected error while assigning task statistics: {e}")
        return None


def statistics_report_task_batch(
    validator,
    miner_uid_list: List[int],
    predictions: List[float],
    task_id: str,
) -> dict | None:
    try:
        payload = {
            "validator_uid": int(validator.uid),
            "miner_uid_list": [int(uid) for uid in miner_uid_list],
            "predictions": [float(p) for p in predictions],
            "task_id": str(task_id),
        }
        with Client(timeout=Timeout(30)) as client:
            response = client.post(
                f"{validator.config.proxy.proxy_client_url}/tasks/statistics/report",
                json=payload,
            )
        response.raise_for_status()
        bt.logging.info("Successfully reported task responses to /statistics/report")
        return response.json()
    except ReadTimeout:
        bt.logging.warning("Statistics report request timed out")
        return None
    except HTTPStatusError as e:
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text
        bt.logging.warning(f"Statistics report request failed: {error_detail}")
        return None
    except Exception as e:
        bt.logging.exception(f"Unexpected error while reporting task statistics: {e}")
        return None


def statistics_report_task_single(
    validator,
    miner_uid: int,
    prediction: float,
    task_id: str,
) -> dict | None:
    try:
        payload = {
            "validator_uid": int(validator.uid),
            "miner_uid": int(miner_uid),
            "prediction": float(prediction),
            "task_id": str(task_id),
        }
        with Client(timeout=Timeout(30)) as client:
            response = client.post(
                f"{validator.config.proxy.proxy_client_url}/tasks/statistics/report",
                json=payload,
            )
        response.raise_for_status()
        bt.logging.info("Successfully reported task response to /statistics/report")
        return response.json()
    except ReadTimeout:
        bt.logging.warning("Statistics report request timed out")
        return None
    except HTTPStatusError as e:
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text
        bt.logging.warning(f"Statistics report request failed: {error_detail}")
        return None
    except Exception as e:
        bt.logging.exception(f"Unexpected error while reporting task statistics: {e}")
        return None
