from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

import bittensor as bt


class _ServerCatalogMixin:
    """Server catalog endpoints."""

    def get_active_servers(
        self, timeout_seconds: Optional[float] = None
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Fetch the current server catalog from the collector.

        Returns server entries containing identifiers, network coordinates and status
        information that can be used by the validator-side scanner.
        """
        url = f"{self.base_url}/servers"
        headers = self.default_headers()
        headers.pop("Authorization", None)
        req = Request(url, headers=headers, method="GET")
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds

        try:
            with urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                body = resp.read().decode("utf-8", errors="ignore")
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    if status < 200 or status >= 300:
                        bt.logging.error(f"collector servers status={status} body={body}")
                    return status, []

                items_raw = data.get("items", []) if isinstance(data, dict) else []
                items: List[Dict[str, Any]] = [
                    item for item in items_raw if isinstance(item, dict) and item.get("id")
                ]

                if status < 200 or status >= 300:
                    bt.logging.error(f"collector servers status={status} body={body}")

                return status, items
        except Exception as e:  # noqa: BLE001
            bt.logging.error(f"collector servers error: {e}")
            return 599, []

    def post_server_vote(
        self,
        server_id: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float] = None,
    ) -> int:
        if not server_id:
            return 400

        url = f"{self.base_url}/validators/servers/{server_id}/vote"
        headers = self.default_headers()
        body = json.dumps(payload).encode("utf-8")
        req = Request(url, data=body, headers=headers, method="POST")
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds

        try:
            with urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                if status < 200 or status >= 300:
                    bt.logging.error(
                        f"collector vote status={status} server_id={server_id} body={resp.read().decode('utf-8', errors='ignore')}"
                    )
                return status
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                body = ""
            bt.logging.error(
                f"collector vote HTTP error server_id={server_id}: {e.code} {e.reason} body={body}"
            )
            return e.code
        except Exception as e:  # noqa: BLE001
            bt.logging.error(f"collector vote error server_id={server_id}: {e}")
            return 599
