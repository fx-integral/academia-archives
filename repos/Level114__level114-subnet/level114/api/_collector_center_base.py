from typing import Dict, Optional


class _CollectorCenterBase:
    """Common configuration shared by Collector Center API mixins."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: Optional[float] = 10.0,
        api_key: Optional[str] = None,
        reports_limit_default: Optional[int] = 25,
    ) -> None:
        if not base_url or not str(base_url).strip():
            raise ValueError("Collector base_url is required. Provide it via --collector.url")
        self.base_url = base_url.rstrip("/") if base_url else ""

        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else 10.0

        if not api_key or not str(api_key).strip():
            raise ValueError("Collector API key is required. Provide it via --collector.api_key")
        self.api_key = str(api_key).strip()
        self.reports_limit_default = int(reports_limit_default) if reports_limit_default is not None else 25

    def default_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
