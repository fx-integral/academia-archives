"""Scoring helpers for Minecraft mechanism."""

from __future__ import annotations

import time
import traceback
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

import bittensor as bt

from level114.validator.mechanisms.minecraft.constants import DEBUG_SCORING, MAX_REPORT_HISTORY
from level114.validator.mechanisms.minecraft.report_schema import ServerReport
from level114.validator.mechanisms.minecraft.scorer import (
    MinerContext,
    apply_score_smoothing,
    calculate_miner_score,
)
from level114.validator.mechanisms.minecraft.types import ScoreCacheEntry

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


class PlayerPowerAggregator:
    """Accumulates player presence across servers to compute normalized power scores."""

    def __init__(self) -> None:
        self._player_servers: Dict[str, List[Tuple[str, float]]] = defaultdict(list)

    @staticmethod
    def _normalize_player_id(player) -> Optional[str]:
        uuid = getattr(player, "uuid", "") or ""
        uuid_norm = uuid.strip().lower()
        if uuid_norm and uuid_norm != ZERO_UUID:
            return uuid_norm
        name = getattr(player, "name", "") or ""
        name_norm = name.strip().lower()
        return name_norm if name_norm else None

    @staticmethod
    def _coerce_power(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, numeric)

    def ingest(self, server_id: str, report: ServerReport) -> None:
        if not report or not report.payload:
            return
        seen: Set[str] = set()
        for player in report.payload.active_players:
            player_id = self._normalize_player_id(player)
            if not player_id or player_id in seen:
                continue
            seen.add(player_id)
            power = self._coerce_power(getattr(player, "power", 0.0))
            if power <= 0.0:
                continue
            self._player_servers[player_id].append((server_id, power))

    def compute(self) -> Tuple[Dict[str, float], Dict[str, float]]:
        server_totals: Dict[str, float] = defaultdict(float)
        for entries in self._player_servers.values():
            if not entries:
                continue
            reported_powers = [power for _, power in entries if power > 0.0]
            if not reported_powers:
                continue
            base_power = sum(reported_powers) / len(reported_powers)
            per_server_share = base_power / len(entries)
            if per_server_share <= 0.0:
                continue
            for server_id, _ in entries:
                server_totals[server_id] += per_server_share

        if not server_totals:
            return {}, {}

        max_total = max(server_totals.values())
        if max_total <= 0.0:
            return {}, {}

        normalized = {server_id: total / max_total for server_id, total in server_totals.items()}
        return normalized, dict(server_totals)


def _assign_zero_score(
    mechanism,
    server_id: str,
    *,
    reason: str,
    scanner_entry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    zero_components = {
        "infrastructure": 0.0,
        "participation": 0.0,
        "reliability": 0.0,
        "player_power": 0.0,
    }
    mechanism.score_cache[server_id] = ScoreCacheEntry(
        score=0,
        raw_score=0,
        components=zero_components,
        updated_at=time.time(),
    )
    result = {
        "server_id": server_id,
        "score": 0,
        "raw_score": 0,
        "components": zero_components,
        "latency": 0.0,
        "compliance": False,
        "reports_count": 0,
        "zero_reason": reason,
    }
    if scanner_entry is not None:
        result["scanner"] = dict(scanner_entry)
    return result


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:  # NaN check
            return None
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def score_server(
    mechanism,
    server_id: str,
    report_fetch_limit: int,
    scanner_entry: Optional[Dict[str, Any]] = None,
    *,
    parsed_reports: Optional[List[ServerReport]] = None,
    player_power_score: Optional[float] = None,
    player_power_total: Optional[float] = None,
    reports_missing: bool = False,
) -> Optional[Dict[str, Any]]:
    try:
        scanner_snapshot = dict(scanner_entry) if scanner_entry else None
        if not scanner_snapshot:
            bt.logging.warning(
                f"[Minecraft] Scanner data missing for server {server_id}; assigning zero score"
            )
            return _assign_zero_score(
                mechanism,
                server_id,
                reason="scanner_missing",
                scanner_entry=scanner_snapshot,
            )

        if not scanner_snapshot.get("online", False):
            bt.logging.warning(
                f"[Minecraft] Scanner marked server {server_id} offline; assigning zero score"
            )
            return _assign_zero_score(
                mechanism,
                server_id,
                reason="scanner_offline",
                scanner_entry=scanner_snapshot,
            )

        parsed_list: Optional[List[ServerReport]] = (
            list(parsed_reports) if parsed_reports is not None else None
        )
        if parsed_list is None:
            status, reports = mechanism.collector_api.get_server_reports(
                server_id,
                limit=report_fetch_limit,
            )

            if status != 200:
                bt.logging.debug(
                    f"[Minecraft] Collector returned status {status} for server {server_id}; reports={len(reports)}"
                )

            if not reports:
                return _handle_missing_reports(mechanism, server_id)

            parsed_list = []
            for report_dict in reports:
                try:
                    parsed_list.append(ServerReport.from_dict(report_dict))
                except Exception as parse_err:  # noqa: BLE001
                    bt.logging.debug(
                        f"[Minecraft] Failed to parse report for server {server_id}: {parse_err}"
                    )

        if not parsed_list:
            if reports_missing:
                return _handle_missing_reports(mechanism, server_id)
            bt.logging.debug(f"[Minecraft] No valid reports parsed for server {server_id}")
            return None

        fresh_reports = filter_fresh_reports(parsed_list)
        if not fresh_reports:
            return _downgrade_outdated_reports(mechanism, server_id)

        latest_report = fresh_reports[0]
        scanner_max_players = _safe_int(scanner_snapshot.get("max_players"))
        scanner_players = _safe_int(scanner_snapshot.get("players"))
        report_max_players = latest_report.payload.max_players
        report_player_count = latest_report.payload.player_count

        if (
            scanner_max_players is not None
            and isinstance(report_max_players, int)
            and scanner_max_players != report_max_players
        ):
            bt.logging.warning(
                (
                    "[Minecraft] Max players mismatch for server {server_id} "
                    "(scanner={scanner}, report={report}); score=0"
                ).format(
                    server_id=server_id,
                    scanner=scanner_max_players,
                    report=report_max_players,
                )
            )
            return _assign_zero_score(
                mechanism,
                server_id,
                reason="max_players_mismatch",
                scanner_entry=scanner_snapshot,
            )

        if (
            scanner_players is not None
            and isinstance(report_player_count, int)
            and report_player_count > scanner_players + 5
        ):
            bt.logging.warning(
                (
                    "[Minecraft] Player count mismatch for server {server_id} "
                    "(scanner={scanner}, report={report}); score=0"
                ).format(
                    server_id=server_id,
                    scanner=scanner_players,
                    report=report_player_count,
                )
            )
            return _assign_zero_score(
                mechanism,
                server_id,
                reason="player_count_mismatch",
                scanner_entry=scanner_snapshot,
            )

        history = deque(reversed(fresh_reports), maxlen=MAX_REPORT_HISTORY)

        context = MinerContext(
            report=latest_report,
            http_latency_s=0.0,
            history=history,
        )

        normalized_player_power = float(player_power_score or 0.0)
        new_score, components = calculate_miner_score(
            context,
            player_power_score=normalized_player_power,
        )
        components["player_power"] = normalized_player_power
        if player_power_total is not None:
            components["player_power_total"] = float(player_power_total)
        previous_entry = mechanism.score_cache.get(server_id)
        previous_score = previous_entry.score if previous_entry else None
        smoothed_score = apply_score_smoothing(new_score, previous_score)

        mechanism.score_cache[server_id] = ScoreCacheEntry(
            score=smoothed_score,
            raw_score=new_score,
            components=components,
            updated_at=time.time(),
        )

        if DEBUG_SCORING:
            bt.logging.debug(
                f"[Minecraft] Scored server {server_id}: {smoothed_score} (raw: {new_score}) "
                f"using {len(history)} reports"
            )

        result = {
            "server_id": server_id,
            "score": smoothed_score,
            "raw_score": new_score,
            "components": components,
            "latency": 0.0,
            "compliance": True,
            "reports_count": len(history),
            "report_max_players": report_max_players,
            "report_player_count": report_player_count,
        }
        if player_power_total is not None:
            result["player_power_total"] = float(player_power_total)
        if scanner_snapshot is not None:
            result["scanner"] = scanner_snapshot
            if scanner_players is not None and isinstance(report_player_count, int):
                result["scanner_delta_players"] = report_player_count - scanner_players
        return result

    except Exception as exc:  # noqa: BLE001
        bt.logging.error(f"[Minecraft] Error scoring server {server_id}: {exc}")
        if DEBUG_SCORING:
            bt.logging.debug(traceback.format_exc())
        return None


def _handle_missing_reports(mechanism, server_id: str) -> Optional[Dict[str, Any]]:
    previous_entry = mechanism.score_cache.get(server_id)
    if previous_entry and previous_entry.score > 0:
        bt.logging.warning(
            f"[Minecraft] Collector returned no reports for server {server_id}; downgrading score to 0",
        )
        return _assign_zero_score(
            mechanism,
            server_id,
            reason="collector_no_reports",
        )

    bt.logging.debug(f"[Minecraft] No reports available for server {server_id}")
    return None


def filter_fresh_reports(reports: List[ServerReport]) -> List[ServerReport]:
    now_ms = int(time.time() * 1000)
    max_age_ms = int(6 * 3600 * 1000)
    fresh_reports = [
        report for report in reports if (now_ms - report.client_timestamp_ms) <= max_age_ms
    ]
    if len(fresh_reports) < len(reports):
        bt.logging.debug(
            f"[Minecraft] Filtered {len(reports) - len(fresh_reports)} stale reports for server"
        )
    return fresh_reports


def _downgrade_outdated_reports(mechanism, server_id: str) -> Dict[str, Any]:
    bt.logging.warning(
        f"[Minecraft] Collector reports for server {server_id} are older than 6h; downgrading score to 0"
    )
    return _assign_zero_score(
        mechanism,
        server_id,
        reason="collector_reports_stale",
    )
