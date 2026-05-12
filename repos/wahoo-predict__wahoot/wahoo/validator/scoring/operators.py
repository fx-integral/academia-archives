from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd

from .dataframe import ensure_required_columns

logger = logging.getLogger(__name__)

HALF_LIFE_SECONDS = 12 * 3600
EPOCH_INTERVAL_SECONDS = 360 * 12
HALF_LIFE_EPOCHS = int(HALF_LIFE_SECONDS / EPOCH_INTERVAL_SECONDS)
EMA_ALPHA = 1 - (0.5 ** (1 / HALF_LIFE_EPOCHS))
PROFIT_EXPONENT = 0.7

CLIFF_RESET_THRESHOLD = 0.5
NEW_MINER_HIGH_SCORE_THRESHOLD = 5000
HIGH_PROFIT_THRESHOLD = 50000


@dataclass(frozen=True)
class OperatorResult:
    weights: np.ndarray
    meta: Dict[str, Any]


class Operator(ABC):
    name: str = "base"
    required_columns: Sequence[str] = (
        "hotkey",
        "profit",
    )

    def preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        ensure_required_columns(df, self.required_columns)
        return df

    @abstractmethod
    def run(self, df: pd.DataFrame) -> OperatorResult:
        raise NotImplementedError


class EMAVolumeScorer(Operator):
    name = "ema_volume"
    required_columns = (
        "hotkey",
        "profit",
    )

    def __init__(self, alpha: float = EMA_ALPHA, profit_exp: float = PROFIT_EXPONENT):
        self.alpha = alpha
        self.profit_exp = profit_exp

    def run(
        self,
        df: pd.DataFrame,
        previous_scores: Optional[Dict[str, float]] = None,
    ) -> OperatorResult:
        df = self.preprocess(df)

        if previous_scores is None:
            previous_scores = {}

        hotkeys = df["hotkey"].to_numpy()
        profit = df["profit"].fillna(0).to_numpy(dtype=float)

        # Only positive profit contributes to score; losses are clipped to 0
        clamped_profit = np.maximum(0.0, profit)
        raw_scores = np.power(clamped_profit, self.profit_exp)

        smoothed_scores = np.zeros_like(raw_scores)
        new_miner_count = 0
        cliff_reset_count = 0

        for i, hotkey in enumerate(hotkeys):
            prev_score = previous_scores.get(hotkey, 0.0)
            raw = raw_scores[i]
            p = profit[i]

            if prev_score == 0.0:
                smoothed_scores[i] = raw
                new_miner_count += 1

                if raw > NEW_MINER_HIGH_SCORE_THRESHOLD:
                    logger.warning(
                        f"ANOMALY: New miner {hotkey[:16]}... has unusually high raw score: "
                        f"raw_score={raw:.2f}, profit=${p:.2f}"
                    )
                elif p > HIGH_PROFIT_THRESHOLD:
                    logger.info(
                        f"New high-profit miner {hotkey[:16]}...: "
                        f"raw_score={raw:.2f}, profit=${p:.2f}"
                    )
            elif prev_score > 0 and raw < CLIFF_RESET_THRESHOLD * prev_score:
                smoothed_scores[i] = raw
                cliff_reset_count += 1
                logger.warning(
                    f"EMA cliff reset for {hotkey[:16]}...: "
                    f"prev_ema={prev_score:.2f}, raw={raw:.4f}, "
                    f"ratio={raw/prev_score:.6f} < {CLIFF_RESET_THRESHOLD}, "
                    f"profit=${p:.2f}"
                )
            else:
                smoothed_scores[i] = (
                    1 - self.alpha
                ) * prev_score + self.alpha * raw

                if prev_score > 0 and raw < 0.1 * prev_score:
                    logger.info(
                        f"Significant score drop for {hotkey[:16]}...: "
                        f"prev_ema={prev_score:.2f}, raw={raw:.2f}, "
                        f"ratio={raw/prev_score:.4f}, profit=${p:.2f}"
                    )

        if cliff_reset_count > 0:
            logger.info(
                f"EMA cliff detection: Reset {cliff_reset_count} miners with "
                f"raw_score < {CLIFF_RESET_THRESHOLD*100:.1f}% of stored EMA"
            )

        total = smoothed_scores.sum()
        if total > 0:
            weights = smoothed_scores / total
        else:
            weights = np.zeros_like(smoothed_scores)

        meta = {
            "total_miners": len(hotkeys),
            "new_miners": new_miner_count,
            "cliff_resets": cliff_reset_count,
            "active_miners": int(np.sum(weights > 0)),
            "total_raw_score": float(raw_scores.sum()),
            "total_smoothed_score": float(total),
            "alpha": self.alpha,
            "profit_exponent": self.profit_exp,
            "cliff_threshold": CLIFF_RESET_THRESHOLD,
            "max_weight": float(weights.max()) if len(weights) > 0 else 0.0,
            "mean_weight": float(weights.mean()) if len(weights) > 0 else 0.0,
            "smoothed_scores": {
                str(hotkey): float(smoothed_scores[i])
                for i, hotkey in enumerate(hotkeys)
            },
        }

        return OperatorResult(weights=weights, meta=meta)


__all__ = [
    "Operator",
    "OperatorResult",
    "EMAVolumeScorer",
    "EMA_ALPHA",
    "HALF_LIFE_EPOCHS",
    "PROFIT_EXPONENT",
    "CLIFF_RESET_THRESHOLD",
]
