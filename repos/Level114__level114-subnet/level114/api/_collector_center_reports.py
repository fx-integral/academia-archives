from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

import bittensor as bt


class _ServerReportsMixin:
    """Historical server reports endpoint."""

    def get_server_reports(
        self,
        server_id: str,
        limit: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        if not server_id:
            return 400, []

        effective_limit = int(limit) if limit is not None else self.reports_limit_default
        query = urlencode({"limit": effective_limit})
        url = f"{self.base_url}/validators/servers/{server_id}/reports?{query}"
        req = Request(url, headers=self.default_headers(), method="GET")
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds

        try:
            with urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                body = resp.read().decode("utf-8", errors="ignore")

                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    if status < 200 or status >= 300:
                        bt.logging.error(
                            f"collector reports status={status} server_id={server_id} body={body}"
                        )
                    return status, []

                items_raw = data.get("items", []) if isinstance(data, dict) else []
                items = [item for item in items_raw if isinstance(item, dict)]

                if status < 200 or status >= 300:
                    bt.logging.error(
                        f"collector reports status={status} server_id={server_id} body={body}"
                    )

                return status, items

        except Exception as e:
            bt.logging.error(f"collector reports error server_id={server_id}: {e}")
            return 599, []
