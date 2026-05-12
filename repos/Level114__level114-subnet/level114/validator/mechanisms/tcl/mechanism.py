"""Mechanism 1 - The Cursed Land metrics handling."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import bittensor as bt

from level114.validator.mechanisms.base import MechanismContext, ValidatorMechanism
from level114.validator.mechanisms.tcl.scoring import safe_float, score_metrics
from level114.validator.mechanisms.tcl.types import TclScoreEntry


class TclMechanism(ValidatorMechanism):
    """Fetch TCL metrics and compute scores."""

    mechanism_id = 1
    mechanism_name = "tcl"

    def __init__(self, context: MechanismContext) -> None:
        super().__init__(context)
        self.collector_api = context.collector_api
        self.metagraph = context.metagraph

        self.last_metrics: Dict[str, Dict[str, Any]] = {}
        self.last_metrics_timestamp: float = 0.0
        self.score_cache: Dict[str, TclScoreEntry] = {}
        self.latest_scores: Dict[str, Dict[str, Any]] = {}

        bt.logging.info("TCL mechanism initialized")

    async def run_cycle(self) -> Dict[str, Any]:
        cycle_start = time.time()
        stats: Dict[str, Any] = {
            "cycle_id": self.cycle_count,
            "timestamp": cycle_start,
            "hotkeys_processed": 0,
            "metrics_collected": 0,
            "servers_processed": 0,
            "scores_updated": 0,
            "errors": 0,
            "total_time": 0.0,
            "scoring_results": {},
            "mechanism_id": self.mechanism_id,
            "mechanism_name": self.mechanism_name,
        }

        try:
            hotkeys = list(self.metagraph.hotkeys)
            collected: Dict[str, Dict[str, Any]] = {}
            scoring_results: Dict[str, Dict[str, Any]] = {}

            for hotkey in hotkeys:
                stats["hotkeys_processed"] += 1
                stats["servers_processed"] += 1
                try:
                    status, payload = self.collector_api.get_tcl_metrics(hotkey)
                    if status != 200 or not isinstance(payload, dict):
                        continue

                    collected[hotkey] = payload
                    stats["metrics_collected"] += 1

                    entry = score_metrics(payload, safe_float)
                    scoring_results[hotkey] = {
                        "score": entry.score,
                        "score_fraction": entry.score_fraction,
                        "components": entry.components,
                        "metrics": entry.metrics,
                    }
                    self.score_cache[hotkey] = entry
                    stats["scores_updated"] += 1
                    bt.logging.debug(
                        f"[TCL] Scored hotkey={hotkey} score={entry.score} fraction={entry.score_fraction:.3f}"
                    )
                except Exception as exc:  # noqa: BLE001
                    bt.logging.error(
                        f"[TCL] Failed to fetch TCL metrics for hotkey={hotkey}: {exc}"
                    )
                    stats["errors"] += 1

            if collected:
                self.last_metrics = collected
                self.last_metrics_timestamp = time.time()

            if scoring_results:
                stale_hotkeys = [
                    hotkey
                    for hotkey in list(self.score_cache.keys())
                    if hotkey not in scoring_results
                ]
                for hotkey in stale_hotkeys:
                    self.score_cache.pop(hotkey, None)

            stats["scoring_results"] = scoring_results
            self.latest_scores = scoring_results

        except Exception as exc:  # noqa: BLE001
            bt.logging.error(f"[TCL] Critical error in TCL cycle: {exc}")
            stats["errors"] += 1

        finally:
            stats["total_time"] = time.time() - cycle_start
            self.cycle_count += 1
            bt.logging.info(
                (
                    "✅ [TCL] Cycle {cycle} complete: {hotkeys} hotkeys, {metrics} metrics collected, "
                    "{errors} errors, {duration:.1f}s"
                ).format(
                    cycle=stats["cycle_id"],
                    hotkeys=stats.get("hotkeys_processed", 0),
                    metrics=stats.get("metrics_collected", 0),
                    errors=stats.get("errors", 0),
                    duration=stats["total_time"],
                )
            )

        return stats

    def get_latest_scores(self) -> Dict[str, Dict[str, Any]]:
        return self.latest_scores

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update(
            {
                "metrics_cached": len(self.last_metrics),
                "last_metrics_timestamp": self.last_metrics_timestamp,
                "cached_scores": len(self.score_cache),
            }
        )
        return status

    def get_cached_score(self, hotkey: str) -> Optional[TclScoreEntry]:
        return self.score_cache.get(hotkey)
