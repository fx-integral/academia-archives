"""Scanner orchestration for the Minecraft mechanism."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Set

import bittensor as bt

from level114.validator.mechanisms.minecraft._scanner_runner import perform_scan
from level114.validator.mechanisms.minecraft._scanner_logger import _BTScannerLogger


class MinecraftScanner:
    """Encapsulates catalog refresh logic for Minecraft servers."""

    def __init__(
        self,
        collector_api: Any,
        logger: _BTScannerLogger,
        interval_seconds: float,
    ) -> None:
        self.collector_api = collector_api
        self.logger = logger
        self.interval_seconds = interval_seconds
        self.last_scan_time: float = 0.0
        self.results: Dict[str, Optional[Dict[str, Any]]] = {}
        self.last_metrics: Dict[str, Any] = {}
        self.last_attempt_ids: Set[str] = set()
        self.missing_ids: Set[str] = set()
        self.last_status: str = "never"
        self.last_error: Optional[str] = None
        self.disabled_scanners: Set[str] = set()

    async def refresh(self, server_ids: List[str]) -> Dict[str, Any]:
        relevant_ids: Set[str] = {sid for sid in server_ids if sid}
        if not relevant_ids:
            return {"status": "no_servers"}

        now = time.time()
        missing_ids = {sid for sid in relevant_ids if sid not in self.results}
        interval_elapsed = now - self.last_scan_time if self.last_scan_time else None
        interval_ready = interval_elapsed is None or interval_elapsed >= self.interval_seconds

        if not interval_ready and not missing_ids:
            return {
                "status": "cached",
                "last_run": self.last_scan_time if self.last_scan_time else None,
                "interval_seconds": self.interval_seconds,
                "missing": list(self.missing_ids),
                "attempted": list(self.last_attempt_ids),
                "metrics": self.last_metrics,
            }

        try:
            payload = await asyncio.to_thread(
                perform_scan,
                self.collector_api,
                self.logger,
                relevant_ids,
            )
        except Exception as exc:  # noqa: BLE001
            bt.logging.error(f"[Minecraft] Scanner execution failed: {exc}")
            self.last_error = str(exc)
            self.last_status = "error"
            return {
                "status": "error",
                "error": str(exc),
                "last_run": self.last_scan_time if self.last_scan_time else None,
                "interval_seconds": self.interval_seconds,
            }

        if payload is None:
            self.last_error = "scanner_failed"
            self.last_status = "error"
            return {
                "status": "error",
                "error": "scanner_failed",
                "last_run": self.last_scan_time if self.last_scan_time else None,
                "interval_seconds": self.interval_seconds,
            }

        self.last_scan_time = payload["timestamp"]
        self.last_metrics = payload["metrics"]
        self.last_attempt_ids = payload["attempted"]
        self.missing_ids = payload["missing"]
        self.last_status = "performed"
        self.last_error = payload.get("error")

        for server_id in relevant_ids:
            self.results[server_id] = payload["results"].get(server_id)

        self.disabled_scanners = set(payload.get("disabled_scanners") or [])

        return {
            "status": "performed" if payload.get("attempted") else "no_attempt",
            "last_run": self.last_scan_time,
            "interval_seconds": self.interval_seconds,
            "missing": list(payload["missing"]),
            "attempted": list(payload["attempted"]),
            "updated": len(
                [sid for sid, entry in payload["results"].items() if entry is not None]
            ),
            "metrics": payload["metrics"],
            "error": payload.get("error"),
            "disabled_scanners": sorted(self.disabled_scanners),
        }
