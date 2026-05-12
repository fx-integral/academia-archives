"""Minecraft mechanism orchestrating collector scoring."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

import bittensor as bt

from level114.validator.mechanisms.base import MechanismContext, ValidatorMechanism
from level114.validator.mechanisms.minecraft._scanner_controller import MinecraftScanner
from level114.validator.mechanisms.minecraft._scanner_logger import _BTScannerLogger
from level114.validator.mechanisms.minecraft._voting_client import VoteClient
from level114.validator.mechanisms.minecraft.mappings import fetch_server_mappings
from level114.validator.mechanisms.minecraft.report_schema import ServerReport
from level114.validator.mechanisms.minecraft.scoring import (
    PlayerPowerAggregator,
    filter_fresh_reports,
    score_server,
)
from level114.validator.mechanisms.minecraft.types import ScoreCacheEntry


class MinecraftMechanism(ValidatorMechanism):
    """Fetch collector reports and compute Minecraft scores."""

    mechanism_id = 0
    mechanism_name = "minecraft"

    def __init__(self, context: MechanismContext) -> None:
        super().__init__(context)
        self.config = context.config
        self.metagraph = context.metagraph
        self.collector_api = context.collector_api

        self.replay_protection = None
        self.score_cache: Dict[str, ScoreCacheEntry] = {}
        self.hotkey_to_server_ids: Dict[str, List[str]] = {}
        self.server_id_to_hotkey: Dict[str, str] = {}
        self.server_ids_last_fetch: float = 0.0
        self.server_ids_min_refresh_interval: float = 12.5
        self.report_fetch_limit: int = getattr(
            getattr(self.config, "collector", None), "reports_limit", 25
        )
        self.latest_scores: Dict[str, Dict[str, Any]] = {}
        self.last_cleanup = time.time()

        validator_cfg = getattr(self.config, "validator", None)
        configured_interval = (
            getattr(validator_cfg, "scanner_interval_seconds", 24 * 60)
            if validator_cfg
            else 24 * 60
        )
        try:
            interval_value = float(configured_interval)
            if not interval_value or interval_value != interval_value:
                raise ValueError
        except (TypeError, ValueError):
            interval_value = 24 * 60.0
        self.scan_interval = max(interval_value, 300.0)

        self._scanner_logger = _BTScannerLogger()
        self.scanner = MinecraftScanner(self.collector_api, self._scanner_logger, self.scan_interval)

        self.vote_client_version = (
            getattr(validator_cfg, "client_version", None) if validator_cfg else None
        )
        if not isinstance(self.vote_client_version, str) or not self.vote_client_version.strip():
            self.vote_client_version = "validator-agent/2.1.0"
        self.vote_client = VoteClient(self.collector_api, self.vote_client_version)

        bt.logging.info("Minecraft mechanism initialized - collector scoring")

    async def run_cycle(self) -> Dict[str, Any]:
        cycle_start = time.time()
        stats: Dict[str, Any] = {
            "cycle_id": self.cycle_count,
            "timestamp": cycle_start,
            "servers_processed": 0,
            "scores_updated": 0,
            "errors": 0,
            "total_time": 0.0,
            "scoring_results": {},
            "mechanism_id": self.mechanism_id,
            "mechanism_name": self.mechanism_name,
            "hotkeys_with_servers": 0,
        }

        try:
            bt.logging.info(f"🔄 [Minecraft] Starting scoring cycle {self.cycle_count}")
            active_hotkeys = list(self.metagraph.hotkeys)
            server_mappings = self._get_server_mappings(active_hotkeys)
            all_server_ids = sorted(
                {
                    server_id
                    for ids in server_mappings.values()
                    for server_id in ids
                    if server_id
                }
            )
            stats["hotkeys_with_servers"] = len(server_mappings)
            stats["servers_found"] = len(all_server_ids)

            if not all_server_ids:
                bt.logging.warning("[Minecraft] No server mappings found for active hotkeys")
                return stats

            stats["scanner"] = await self.scanner.refresh(all_server_ids)
            (
                parsed_reports_map,
                player_power_scores,
                player_power_totals,
                missing_reports,
            ) = self._prepare_reports_and_power(all_server_ids)
            stats["player_power_servers"] = len(player_power_scores)

            scoring_results: Dict[str, Dict[str, Any]] = {}
            pending_votes: List[Tuple[str, Dict[str, Any]]] = []
            for hotkey, server_ids in server_mappings.items():
                per_hotkey_results: Dict[str, Dict[str, Any]] = {}
                best_score = 0.0
                best_server_id: Optional[str] = None
                zero_triggered = False
                zero_servers: List[str] = []
                for server_id in server_ids:
                    result = await self._score_server(
                        server_id,
                        parsed_reports=parsed_reports_map.get(server_id),
                        player_power_score=player_power_scores.get(server_id, 0.0),
                        player_power_total=player_power_totals.get(server_id),
                        reports_missing=server_id in missing_reports,
                    )
                    stats["servers_processed"] += 1
                    if not result:
                        continue
                    per_hotkey_results[server_id] = result
                    pending_votes.append((server_id, result))
                    stats["scores_updated"] += 1
                    try:
                        score_value = float(result.get("score", 0) or 0.0)
                    except (TypeError, ValueError):
                        score_value = 0.0
                    if score_value <= 0.0:
                        zero_triggered = True
                        zero_servers.append(server_id)
                    if best_server_id is None or score_value > best_score:
                        best_score = score_value
                        best_server_id = server_id
                if per_hotkey_results:
                    aggregate_score = 0.0 if zero_triggered else best_score
                    primary_server_id = (
                        zero_servers[0] if zero_triggered and zero_servers else best_server_id
                    )
                    scoring_results[hotkey] = {
                        "score": aggregate_score,
                        "best_server_id": primary_server_id,
                        "zero_enforced": zero_triggered,
                        "zero_servers": zero_servers,
                        "servers": per_hotkey_results,
                    }

            stats["votes"] = await self.vote_client.submit_votes(pending_votes)

            stats["scoring_results"] = scoring_results
            self.latest_scores = scoring_results

            if time.time() - self.last_cleanup > 3600:
                self._cleanup_old_data()
                self.last_cleanup = time.time()

        except Exception as exc:  # noqa: BLE001
            bt.logging.error(f"[Minecraft] Critical error in scoring cycle: {exc}")
            stats["errors"] += 1
        finally:
            stats["total_time"] = time.time() - cycle_start
            self.cycle_count += 1
            bt.logging.info(
                (
                    "✅ [Minecraft] Cycle {cycle} complete: {processed} servers, {updated} "
                    "scores updated, {errors} errors, {duration:.1f}s"
                ).format(
                    cycle=stats["cycle_id"],
                    processed=stats.get("servers_processed", 0),
                    updated=stats.get("scores_updated", 0),
                    errors=stats.get("errors", 0),
                    duration=stats["total_time"],
                )
            )

        return stats

    def get_latest_scores(self) -> Dict[str, Dict[str, Any]]:
        return self.latest_scores

    def _get_server_mappings(self, hotkeys: List[str]) -> Dict[str, List[str]]:
        return fetch_server_mappings(self, hotkeys)

    async def _score_server(
        self,
        server_id: str,
        *,
        parsed_reports: Optional[List[ServerReport]] = None,
        player_power_score: Optional[float] = None,
        player_power_total: Optional[float] = None,
        reports_missing: bool = False,
    ) -> Optional[Dict[str, Any]]:
        return score_server(
            mechanism=self,
            server_id=server_id,
            report_fetch_limit=self.report_fetch_limit,
            scanner_entry=self.scan_results.get(server_id),
            parsed_reports=parsed_reports,
            player_power_score=player_power_score,
            player_power_total=player_power_total,
            reports_missing=reports_missing,
        )

    def _prepare_reports_and_power(
        self,
        server_ids: List[str],
    ) -> Tuple[Dict[str, List[ServerReport]], Dict[str, float], Dict[str, float], Set[str]]:
        parsed_reports: Dict[str, List[ServerReport]] = {}
        aggregator = PlayerPowerAggregator()
        missing_reports: Set[str] = set()

        for server_id in server_ids:
            parsed_list: List[ServerReport] = []
            reports: Optional[List[Dict[str, Any]]] = None
            try:
                status, reports = self.collector_api.get_server_reports(
                    server_id,
                    limit=self.report_fetch_limit,
                )
                report_count = len(reports) if reports else 0
                if status != 200:
                    bt.logging.debug(
                        f"[Minecraft] Collector returned status {status} for server {server_id}; reports={report_count}"
                    )
                for report_dict in reports or []:
                    try:
                        parsed_list.append(ServerReport.from_dict(report_dict))
                    except Exception as parse_err:  # noqa: BLE001
                        bt.logging.debug(
                            f"[Minecraft] Failed to parse report for server {server_id}: {parse_err}"
                        )
            except Exception as exc:  # noqa: BLE001
                bt.logging.error(f"[Minecraft] Error fetching reports for server {server_id}: {exc}")
                reports = None
            if not reports:
                missing_reports.add(server_id)
            parsed_reports[server_id] = parsed_list

            if parsed_list:
                fresh_reports = filter_fresh_reports(parsed_list)
                if fresh_reports:
                    aggregator.ingest(server_id, fresh_reports[0])

        normalized_scores, raw_totals = aggregator.compute()
        return parsed_reports, normalized_scores, raw_totals, missing_reports

    def _cleanup_old_data(self) -> None:
        try:
            bt.logging.info("🧹 [Minecraft] Cleaning up old data...")
            if self.replay_protection:
                self.replay_protection.cleanup_old_entries(max_age_hours=168)

            current_time = time.time()
            stale_ids = [
                server_id
                for server_id, entry in self.score_cache.items()
                if current_time - entry.updated_at > 3600
            ]
            for server_id in stale_ids:
                self.score_cache.pop(server_id, None)

            bt.logging.info("✅ [Minecraft] Cleanup complete")
        except Exception as exc:  # noqa: BLE001
            bt.logging.error(f"[Minecraft] Error during cleanup: {exc}")

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update({
            "cached_scores": len(self.score_cache),
            "hotkeys_cached": len(self.hotkey_to_server_ids),
            "cached_mappings": sum(len(ids) for ids in self.hotkey_to_server_ids.values()),
            "latest_scores": len(self.latest_scores),
            "replay_protection_active": bool(self.replay_protection),
            "config": {"netuid": self.config.netuid},
            "scanner_last_run": self.scanner.last_scan_time or None,
            "scanner_interval_seconds": self.scan_interval,
            "scanner_cached": sum(1 for entry in self.scan_results.values() if entry is not None),
            "scanner_missing": sum(1 for entry in self.scan_results.values() if entry is None),
            "scanner_last_status": self.scanner.last_status,
            "scanner_last_error": self.scanner.last_error,
            "scanner_metrics": self.scanner.last_metrics,
            "scanner_disabled": sorted(self.scanner.disabled_scanners),
        })
        return status

    def get_server_id_for_hotkey(self, hotkey: str) -> Optional[str]:
        best_entry = self.latest_scores.get(hotkey)
        if isinstance(best_entry, dict):
            best_server_id = best_entry.get("best_server_id")
            if isinstance(best_server_id, str) and best_server_id:
                return best_server_id
        server_ids = self.hotkey_to_server_ids.get(hotkey)
        if server_ids:
            return server_ids[0]
        return None

    def get_cached_score(self, server_id: str) -> Optional[ScoreCacheEntry]:
        return self.score_cache.get(server_id)

    scan_results = property(lambda self: self.scanner.results)
    scan_last_metrics = property(lambda self: self.scanner.last_metrics)
    scan_last_attempt_ids = property(lambda self: self.scanner.last_attempt_ids)
    scan_missing_ids = property(lambda self: self.scanner.missing_ids)
    scan_last_status = property(lambda self: self.scanner.last_status)
    scan_last_error = property(lambda self: self.scanner.last_error)
    scan_disabled_scanners = property(lambda self: self.scanner.disabled_scanners)
