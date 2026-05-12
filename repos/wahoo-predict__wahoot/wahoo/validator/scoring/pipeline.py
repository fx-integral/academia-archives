from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

from .dataframe import records_to_dataframe
from .models import ValidationRecord
from .operators import Operator, OperatorResult


class OperatorPipeline:
    def __init__(
        self,
        operators: Optional[Iterable[Operator]] = None,
        target_length: int = 256,
    ):
        self._operators: Dict[str, Operator] = {}
        self.target_length = target_length
        if operators:
            for operator in operators:
                self.register(operator)

    def register(self, operator: Operator) -> None:
        self._operators[operator.name] = operator

    def available(self) -> List[str]:
        return list(self._operators.keys())

    def run(
        self,
        operator_name: str,
        records: Sequence[ValidationRecord],
        *,
        dataframe_kwargs: Optional[Dict[str, Any]] = None,
    ) -> OperatorResult:
        if operator_name not in self._operators:
            raise ValueError(
                f"Unknown operator '{operator_name}'. Available: {self.available()}"
            )
        df = records_to_dataframe(records, **(dataframe_kwargs or {}))
        operator = self._operators[operator_name]
        result = operator.run(df)
        weights = self._pad_or_trim(result.weights)
        meta = dict(result.meta)
        meta["operator"] = operator_name
        meta["num_records"] = df.shape[0]
        return OperatorResult(weights=weights, meta=meta)

    def _pad_or_trim(self, weights: np.ndarray) -> np.ndarray:
        if weights.size == self.target_length:
            return weights
        if weights.size > self.target_length:
            trimmed = weights[: self.target_length]
            total = float(trimmed.sum())
            return trimmed / total if total > 0 else trimmed
        pad = np.zeros(self.target_length - weights.size, dtype=float)
        return np.concatenate([weights, pad])


__all__ = ["OperatorPipeline"]
