from typing import Any, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

import bittensor as bt


class _ServerMetricsMixin:
    """Server metrics endpoints."""

    def get_tcl_metrics(
        self, hotkey: str, timeout_seconds: Optional[float] = None
    ) -> Tuple[int, Any]:
        if not hotkey:
            return 400, None
        query = urlencode({"hotkey": hotkey})
        url = f"{self.base_url}/validators/tcl/metrics?{query}"
        headers = self.default_headers()
        req = Request(url, headers=headers, method="GET")
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        try:
            with urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                body = resp.read().decode("utf-8", errors="ignore")
                try:
                    data = json.loads(body)
                    if status < 200 or status >= 300:
                        bt.logging.error(
                            f"collector tcl metrics status={status} hotkey={hotkey} body={body}"
                        )
                    return status, data
                except json.JSONDecodeError:
                    if status < 200 or status >= 300:
                        bt.logging.error(
                            f"collector tcl metrics status={status} hotkey={hotkey} body={body}"
                        )
                    return status, None
        except HTTPError as e:
            if e.code == 404:
                return e.code, None
            bt.logging.error(
                f"collector tcl metrics HTTP error hotkey={hotkey}: {e.code} {e.reason}"
            )
            return e.code, None
        except Exception as e:  # noqa: BLE001
            bt.logging.error(f"collector tcl metrics error hotkey={hotkey}: {e}")
            return 599, None
