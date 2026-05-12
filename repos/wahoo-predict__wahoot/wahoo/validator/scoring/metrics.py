from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import sqlite3

logger = logging.getLogger(__name__)

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.figure import Figure

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    Figure = Any  # type: ignore


def get_score_history(
    db_path: Optional[Path],
    hotkey: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """
    Retrieve score history from the database.

    Args:
        db_path: Path to the validator database
        hotkey: Optional hotkey to filter by
        start_date: Optional start date for filtering
        end_date: Optional end date for filtering
        limit: Optional limit on number of records

    Returns:
        DataFrame with columns: ts, hotkey, score, reason
    """
    from ..database.validator_db import get_or_create_database

    conn = get_or_create_database(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT ts, hotkey, score, reason FROM scoring_runs WHERE 1=1"
    params: List[Any] = []

    if hotkey:
        query += " AND hotkey = ?"
        params.append(hotkey)

    if start_date:
        query += " AND ts >= ?"
        params.append(start_date.isoformat() + "Z")

    if end_date:
        query += " AND ts <= ?"
        params.append(end_date.isoformat() + "Z")

    query += " ORDER BY ts DESC"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return pd.DataFrame(columns=["ts", "hotkey", "score", "reason"])

    data = [dict(row) for row in rows]
    df = pd.DataFrame(data)

    # Convert timestamp to datetime
    if not df.empty and "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)

    return df


def get_latest_scores_by_hotkey(
    db_path: Optional[Path],
) -> pd.DataFrame:
    """
    Get the latest score for each hotkey.

    Args:
        db_path: Path to the validator database

    Returns:
        DataFrame with columns: hotkey, score, ts, reason
    """
    from ..database.validator_db import get_or_create_database

    conn = get_or_create_database(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT sr.hotkey, sr.score, sr.ts, sr.reason
        FROM scoring_runs sr
        INNER JOIN (
            SELECT hotkey, MAX(ts) as max_ts
            FROM scoring_runs
            GROUP BY hotkey
        ) latest ON sr.hotkey = latest.hotkey AND sr.ts = latest.max_ts
        ORDER BY sr.score DESC NULLS LAST
    """

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return pd.DataFrame(columns=["hotkey", "score", "ts", "reason"])

    data = [dict(row) for row in rows]
    df = pd.DataFrame(data)

    # Convert timestamp to datetime
    if not df.empty and "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)

    return df


def calculate_score_metrics(
    df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Calculate statistical metrics for score data.

    Args:
        df: DataFrame with score data (must have 'score' column)

    Returns:
        Dictionary with calculated metrics
    """
    if df.empty or "score" not in df.columns:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "q25": None,
            "q75": None,
        }

    scores = df["score"].dropna()

    if scores.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "q25": None,
            "q75": None,
        }

    return {
        "count": len(scores),
        "mean": float(scores.mean()),
        "median": float(scores.median()),
        "std": float(scores.std()),
        "min": float(scores.min()),
        "max": float(scores.max()),
        "q25": float(scores.quantile(0.25)),
        "q75": float(scores.quantile(0.75)),
    }


def plot_score_timeseries(
    df: pd.DataFrame,
    hotkey: Optional[str] = None,
    output_path: Optional[Path] = None,
    figsize: Tuple[int, int] = (12, 6),
) -> Optional[Figure]:
    """
    Plot score time series.

    Args:
        df: DataFrame with score data (must have 'ts' and 'score' columns)
        hotkey: Optional hotkey to include in title
        output_path: Optional path to save the plot
        figsize: Figure size (width, height)

    Returns:
        matplotlib Figure if matplotlib is available, None otherwise
    """
    if not HAS_MATPLOTLIB:
        logger.warning(
            "matplotlib is not installed. Install it to enable plotting functionality."
        )
        return None

    if df.empty or "ts" not in df.columns or "score" not in df.columns:
        logger.warning("DataFrame is empty or missing required columns")
        return None

    fig, ax = plt.subplots(figsize=figsize)

    # Sort by timestamp
    df_sorted = df.sort_values("ts")

    ax.plot(
        df_sorted["ts"], df_sorted["score"], marker="o", linestyle="-", markersize=4
    )

    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Score")
    title = "Score Time Series"
    if hotkey:
        title += f" - {hotkey}"
    ax.set_title(title)
    ax.grid(True, alpha=0.3)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=45)

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        logger.info(f"Plot saved to {output_path}")

    return fig


def plot_score_distribution(
    df: pd.DataFrame,
    output_path: Optional[Path] = None,
    figsize: Tuple[int, int] = (10, 6),
) -> Optional[Figure]:
    """
    Plot score distribution histogram.

    Args:
        df: DataFrame with score data (must have 'score' column)
        output_path: Optional path to save the plot
        figsize: Figure size (width, height)

    Returns:
        matplotlib Figure if matplotlib is available, None otherwise
    """
    if not HAS_MATPLOTLIB:
        logger.warning(
            "matplotlib is not installed. Install it to enable plotting functionality."
        )
        return None

    if df.empty or "score" not in df.columns:
        logger.warning("DataFrame is empty or missing required columns")
        return None

    scores = df["score"].dropna()

    if scores.empty:
        logger.warning("No valid scores to plot")
        return None

    fig, ax = plt.subplots(figsize=figsize)

    ax.hist(scores, bins=50, edgecolor="black", alpha=0.7)
    ax.set_xlabel("Score")
    ax.set_ylabel("Frequency")
    ax.set_title("Score Distribution")
    ax.grid(True, alpha=0.3)

    # Add statistics text
    mean_score = scores.mean()
    median_score = scores.median()
    stats_text = f"Mean: {mean_score:.6f}\nMedian: {median_score:.6f}"
    ax.text(
        0.02,
        0.98,
        stats_text,
        transform=ax.transAxes,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
    )

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        logger.info(f"Plot saved to {output_path}")

    return fig


def plot_top_miners_scores(
    df: pd.DataFrame,
    top_n: int = 20,
    output_path: Optional[Path] = None,
    figsize: Tuple[int, int] = (12, 8),
) -> Optional[Figure]:
    """
    Plot bar chart of top N miners by score.

    Args:
        df: DataFrame with latest scores (must have 'hotkey' and 'score' columns)
        top_n: Number of top miners to show
        output_path: Optional path to save the plot
        figsize: Figure size (width, height)

    Returns:
        matplotlib Figure if matplotlib is available, None otherwise
    """
    if not HAS_MATPLOTLIB:
        logger.warning(
            "matplotlib is not installed. Install it to enable plotting functionality."
        )
        return None

    if df.empty or "hotkey" not in df.columns or "score" not in df.columns:
        logger.warning("DataFrame is empty or missing required columns")
        return None

    df_sorted = df.sort_values("score", ascending=False).head(top_n)

    fig, ax = plt.subplots(figsize=figsize)

    display_hotkeys = [
        hk[:20] + "..." if len(hk) > 20 else hk for hk in df_sorted["hotkey"]
    ]

    bars = ax.barh(range(len(df_sorted)), df_sorted["score"])
    ax.set_yticks(range(len(df_sorted)))
    ax.set_yticklabels(display_hotkeys)
    ax.set_xlabel("Score")
    ax.set_title(f"Top {top_n} Miners by Score")
    ax.grid(True, alpha=0.3, axis="x")

    for i, (bar, score) in enumerate(zip(bars, df_sorted["score"])):
        width = bar.get_width()
        ax.text(
            width,
            bar.get_y() + bar.get_height() / 2,
            f"{score:.6f}",
            ha="left",
            va="center",
            fontsize=8,
        )

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        logger.info(f"Plot saved to {output_path}")

    return fig


def plot_score_trends_by_hotkey(
    df: pd.DataFrame,
    top_n: int = 10,
    output_path: Optional[Path] = None,
    figsize: Tuple[int, int] = (14, 8),
) -> Optional[Figure]:
    """
    Plot score trends over time for top N miners.

    Args:
        df: DataFrame with score history (must have 'ts', 'hotkey', 'score' columns)
        top_n: Number of top miners to plot
        output_path: Optional path to save the plot
        figsize: Figure size (width, height)

    Returns:
        matplotlib Figure if matplotlib is available, None otherwise
    """
    if not HAS_MATPLOTLIB:
        logger.warning(
            "matplotlib is not installed. Install it to enable plotting functionality."
        )
        return None

    if (
        df.empty
        or "ts" not in df.columns
        or "hotkey" not in df.columns
        or "score" not in df.columns
    ):
        logger.warning("DataFrame is empty or missing required columns")
        return None

    latest_scores = df.groupby("hotkey")["score"].last().sort_values(ascending=False)
    top_hotkeys = latest_scores.head(top_n).index.tolist()

    df_filtered = df[df["hotkey"].isin(top_hotkeys)].copy()
    df_filtered = df_filtered.sort_values("ts")

    fig, ax = plt.subplots(figsize=figsize)

    for hotkey in top_hotkeys:
        hotkey_data = df_filtered[df_filtered["hotkey"] == hotkey]
        if not hotkey_data.empty:
            display_hotkey = hotkey[:15] + "..." if len(hotkey) > 15 else hotkey
            ax.plot(
                hotkey_data["ts"],
                hotkey_data["score"],
                marker="o",
                label=display_hotkey,
                markersize=3,
            )

    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Score")
    ax.set_title(f"Score Trends - Top {top_n} Miners")
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=45)

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        logger.info(f"Plot saved to {output_path}")

    return fig


__all__ = [
    "get_score_history",
    "get_latest_scores_by_hotkey",
    "calculate_score_metrics",
    "plot_score_timeseries",
    "plot_score_distribution",
    "plot_top_miners_scores",
    "plot_score_trends_by_hotkey",
    "HAS_MATPLOTLIB",
]
