from __future__ import annotations

from typing import Dict, Iterable, Sequence

import pandas as pd

from .models import PerformanceMetrics, ValidationRecord

FLOAT_COLUMNS = [
    "total_volume_usd",
    "weighted_volume",
    "profit",
    "realized_profit_usd",
    "unrealized_profit_usd",
    "win_rate",
    "total_fees_paid_usd",
    "referral_volume_usd",
]

INT_COLUMNS = ["trade_count", "open_positions_count", "referral_count"]
TEXT_COLUMNS = [
    "hotkey",
    "signature",
    "message",
    "wahoo_user_id",
    "last_active_timestamp",
]

ALL_COLUMNS = TEXT_COLUMNS + INT_COLUMNS + FLOAT_COLUMNS


def _performance_dict(perf: PerformanceMetrics) -> Dict[str, object]:
    data = perf.model_dump(by_alias=True)
    return {
        key: data.get(key)
        for key in FLOAT_COLUMNS + INT_COLUMNS + ["last_active_timestamp"]
    }


def flatten_record(record: ValidationRecord) -> Dict[str, object]:
    perf = _performance_dict(record.performance)
    return {
        "hotkey": record.hotkey,
        "signature": record.signature,
        "message": record.message,
        "wahoo_user_id": record.wahoo_user_id,
        **perf,
    }


def records_to_dataframe(
    records: Sequence[ValidationRecord],
    *,
    fill_missing: bool = True,
    enforce_types: bool = True,
    drop_duplicates: bool = True,
) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=ALL_COLUMNS)

    rows = [flatten_record(record) for record in records]
    df = pd.DataFrame(rows)

    missing_columns = [col for col in ALL_COLUMNS if col not in df.columns]
    for column in missing_columns:
        df[column] = None

    df = df[ALL_COLUMNS]

    if enforce_types:
        for col in FLOAT_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in INT_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    if fill_missing:
        df[FLOAT_COLUMNS] = df[FLOAT_COLUMNS].fillna(0.0)
        df[INT_COLUMNS] = df[INT_COLUMNS].fillna(0).astype("Int64")
        df["last_active_timestamp"] = df["last_active_timestamp"].fillna("")
        df[["signature", "message", "wahoo_user_id"]] = df[
            ["signature", "message", "wahoo_user_id"]
        ].fillna("")

    if drop_duplicates:
        df = df.sort_values("hotkey").drop_duplicates(subset="hotkey", keep="last")

    return df.reset_index(drop=True)


def ensure_required_columns(
    df: pd.DataFrame, required: Iterable[str] | None = None
) -> None:
    columns = set(df.columns)
    required = set(
        required
        or [
            "hotkey",
            "total_volume_usd",
            "weighted_volume",
            "profit",
            "realized_profit_usd",
            "unrealized_profit_usd",
        ]
    )
    missing = required - columns
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")


__all__ = ["records_to_dataframe", "ensure_required_columns", "flatten_record"]
