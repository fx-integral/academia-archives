"""Vote submission helper for the Minecraft mechanism."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import bittensor as bt


class VoteClient:
    """Handles vote payload construction and submission."""

    def __init__(self, collector_api: Any, client_version: str) -> None:
        self.collector_api = collector_api
        self.client_version = client_version

    async def submit_votes(
        self, vote_entries: List[Tuple[str, Dict[str, Any]]]
    ) -> Dict[str, int]:
        summary = {"submitted": 0, "skipped": 0, "errors": 0}
        if not vote_entries:
            return summary

        if not self.collector_api:
            bt.logging.error("[Minecraft] Collector API unavailable; skipping votes")
            summary["errors"] = len(vote_entries)
            return summary

        for server_id, result in vote_entries:
            payload = self._build_vote_payload(server_id, result)
            if not payload:
                summary["skipped"] += 1
                continue

            try:
                status = await asyncio.to_thread(
                    self.collector_api.post_server_vote,
                    server_id,
                    payload,
                )
            except Exception as exc:  # noqa: BLE001
                bt.logging.error(
                    f"[Minecraft] Failed to submit vote for {server_id}: {exc}"
                )
                summary["errors"] += 1
                continue

            if 200 <= status < 300:
                summary["submitted"] += 1
            else:
                bt.logging.error(
                    f"[Minecraft] Vote rejected for {server_id}: status={status}"
                )
                summary["errors"] += 1

        return summary

    def _build_vote_payload(
        self, server_id: str, result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        scanner_entry = result.get("scanner") or {}
        zero_reason = result.get("zero_reason")
        score = result.get("score", 0)
        compliant = bool(result.get("compliance"))

        verdict: Optional[str] = None
        reason: Optional[str] = None
        value_expected: Dict[str, Any] = {}
        value_got: Dict[str, Any] = {}

        report_max_players = result.get("report_max_players")
        report_player_count = result.get("report_player_count")

        def _compact(values: Dict[str, Any]) -> Dict[str, Any]:
            return {key: val for key, val in values.items() if val is not None}

        if zero_reason:
            verdict = "suspicious"
            if zero_reason == "max_players_mismatch":
                scanner_max = scanner_entry.get("max_players")
                if (
                    isinstance(scanner_max, int)
                    and isinstance(report_max_players, int)
                ):
                    reason = (
                        "Scanner observed max player capacity "
                        f"{scanner_max} while collector report indicated {report_max_players}."
                    )
                elif isinstance(report_max_players, int):
                    reason = (
                        "Collector report indicated max player capacity "
                        f"{report_max_players}, but the scanner value was unavailable."
                    )
                else:
                    reason = "Scanner and collector disagreed on max player capacity."
                value_expected = {"max_players": scanner_max}
                value_got = {"max_players": report_max_players}

            elif zero_reason == "player_count_mismatch":
                scanner_players = scanner_entry.get("players")
                if (
                    isinstance(scanner_players, int)
                    and isinstance(report_player_count, int)
                ):
                    reason = (
                        "Collector report returned player count "
                        f"{report_player_count}, exceeding scanner observation "
                        f"{scanner_players} by more than 5."
                    )
                else:
                    reason = (
                        "Collector report player counts exceeded scanner observations "
                        "beyond the configured tolerance."
                    )
                value_expected = {"players": scanner_entry.get("players"), "tolerance": 5}
                value_got = {"players": report_player_count}

            elif zero_reason == "scanner_offline":
                scanner_online = scanner_entry.get("online")
                reason = (
                    "Scanner reported the server offline while collector telemetry remained available."
                )
                value_expected = {"online": True}
                value_got = {"scanner_online": scanner_online, "report_players": report_player_count}

            elif zero_reason == "scanner_missing":
                reason = (
                    "Scanner did not return data for this server during the validation window."
                )

            elif zero_reason == "collector_no_reports":
                reason = (
                    "Collector returned no fresh reports for this server during the validation window."
                )

            elif zero_reason == "collector_reports_stale":
                reason = (
                    "Collector reports were older than 6 hours, suggesting stale or missing telemetry."
                )
                value_got = {"report_age_hours": 6}

            else:
                reason = f"Server flagged as suspicious due to {zero_reason}."

        elif score > 0 and compliant:
            verdict = "trusted"
            scanner_players = scanner_entry.get("players")
            scanner_max = scanner_entry.get("max_players")
            parts: List[str] = []
            if isinstance(scanner_players, int) and isinstance(report_player_count, int):
                parts.append(
                    f"player counts matched at {report_player_count}"
                )
            if isinstance(scanner_max, int) and isinstance(report_max_players, int):
                parts.append(
                    f"max player capacity matched at {report_max_players}"
                )
            if parts:
                reason = "Scanner and collector metrics aligned: " + ", ".join(parts) + "."
            else:
                reason = (
                    "Scanner and collector metrics aligned within thresholds during this cycle."
                )
            value_expected = {
                "players": scanner_players,
                "max_players": scanner_max,
            }
            value_got = {
                "players": report_player_count,
                "max_players": report_max_players,
            }

        else:
            return None

        if not verdict or not reason:
            return None

        evidence_url = ""
        try:
            evidence_url = f"{self.collector_api.base_url}/validators/servers/{server_id}/reports"
        except Exception:  # noqa: BLE001
            evidence_url = ""

        payload = {
            "verdict": verdict,
            "reason": reason,
            "report_evidence": evidence_url,
            "value_expected": _compact(value_expected),
            "value_got": _compact(value_got),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "client_version": self.client_version,
        }
        return payload
