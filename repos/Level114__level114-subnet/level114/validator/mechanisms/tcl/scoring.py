"""Scoring helpers for TCL mechanism."""

from __future__ import annotations

import time
from typing import Any, Dict

import numpy as np

from level114.validator.mechanisms.tcl.types import COMPONENT_WEIGHTS, MAX_VALUES, TclScoreEntry


def score_metrics(metrics: Dict[str, Any], safe_float) -> TclScoreEntry:
    online_players = safe_float(metrics.get("online_players_count"))
    players_info = metrics.get("online_players") or []
    players_iter = list(players_info) if isinstance(players_info, list) else []

    if players_iter and not online_players:
        online_players = float(len(players_iter))

    total_playtime_seconds = 0.0
    valid_playtime_count = 0
    for player in players_iter:
        playtime_value = safe_float(player.get("playtime"))
        if playtime_value <= 0:
            continue
        total_playtime_seconds += playtime_value
        valid_playtime_count += 1

    avg_playtime_minutes = (
        (total_playtime_seconds / valid_playtime_count) / 60.0
        if valid_playtime_count
        else 0.0
    )

    daily_unique_logins = safe_float(metrics.get("daily_unique_logins"))
    monthly_new_users = safe_float(metrics.get("monthly_new_users"))

    normalized_components = {
        "online_players": min(online_players / MAX_VALUES["online_players"], 1.0),
        "avg_playtime_minutes": min(
            avg_playtime_minutes / MAX_VALUES["avg_playtime_minutes"], 1.0
        ),
        "daily_unique_logins": min(
            daily_unique_logins / MAX_VALUES["daily_unique_logins"], 1.0
        ),
        "monthly_new_users": min(
            monthly_new_users / MAX_VALUES["monthly_new_users"], 1.0
        ),
    }

    score_fraction = sum(
        COMPONENT_WEIGHTS[key] * normalized_components[key]
        for key in COMPONENT_WEIGHTS
    )
    score_fraction = min(max(score_fraction, 0.0), 1.0)
    score_value = int(round(score_fraction * 1000))

    components_detail = {
        key: {
            "value": (
                online_players
                if key == "online_players"
                else avg_playtime_minutes
                if key == "avg_playtime_minutes"
                else daily_unique_logins
                if key == "daily_unique_logins"
                else monthly_new_users
            ),
            "max": MAX_VALUES[key],
            "weight": COMPONENT_WEIGHTS[key],
            "normalized": normalized_components[key],
        }
        for key in COMPONENT_WEIGHTS.keys()
    }

    metrics_summary = {
        "online_players": online_players,
        "avg_playtime_minutes": avg_playtime_minutes,
        "daily_unique_logins": daily_unique_logins,
        "monthly_new_users": monthly_new_users,
    }

    return TclScoreEntry(
        score=score_value,
        score_fraction=score_fraction,
        components=components_detail,
        metrics=metrics_summary,
        updated_at=time.time(),
    )


def safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        numeric = float(value)
        if not np.isfinite(numeric):
            return 0.0
        return numeric
    except (TypeError, ValueError):
        return 0.0
