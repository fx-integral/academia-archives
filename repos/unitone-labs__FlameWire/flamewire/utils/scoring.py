# The MIT License (MIT)
# Copyright © 2026 UnitOne Labs

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from flamewire.gateway.types import MinerNode

SUPPORTED_REGIONS = ("us", "eu", "as")
DEFAULT_METRIC_WEIGHTS = {
    "correctness": 0.4,
    "uptime": 0.3,
    "latency": 0.3,
}
DEFAULT_REGION_WEIGHTS = {
    "us": 1.0 / 3.0,
    "eu": 1.0 / 3.0,
    "as": 1.0 / 3.0,
}
REGIONAL_MULTIPLIER_MIN = 0.5
REGIONAL_MULTIPLIER_MAX = 2.0
DIVERSITY_BONUS_BY_COVERAGE = {
    1: 1.0,
    2: 1.1,
    3: 1.2,
}


@dataclass
class NodeScore:
    """Scoring details for a single node."""

    miner_hotkey: str
    node_id: str
    region: str
    correctness: float
    uptime: float
    latency: float
    total: float


@dataclass
class MinerScore:
    """Aggregated scoring details for a miner."""

    miner_hotkey: str
    # Regional score after applying diminishing returns and regional multipliers.
    regions: Dict[str, float]
    # Raw contribution before applying regional multipliers.
    region_base_scores: Dict[str, float]
    # Regional multiplier for each region.
    region_multipliers: Dict[str, float]
    regions_covered: int
    diversity_bonus: float
    # Final raw miner score before EMA smoothing.
    total: float


def _normalize_weights(weights: Dict[str, float], keys: List[str]) -> Dict[str, float]:
    """Normalize a subset of weights to sum to 1."""
    filtered = {k: max(float(weights.get(k, 0.0)), 0.0) for k in keys}
    total = sum(filtered.values())
    if total <= 0:
        uniform = 1.0 / len(keys)
        return {k: uniform for k in keys}
    return {k: v / total for k, v in filtered.items()}


def _compute_latency_scores(miner_nodes: List[MinerNode]) -> List[float]:
    """
    Compute relative latency scores in [0, 1].

    Fastest node receives 1.0, slowest receives 0.0, and values in-between are linearly scaled.
    """
    latency_values = [n.avg_latency_ms for n in miner_nodes if n.avg_latency_ms is not None]
    if not latency_values:
        return [0.0 for _ in miner_nodes]

    min_latency = min(latency_values)
    max_latency = max(latency_values)
    if max_latency == min_latency:
        return [1.0 if n.avg_latency_ms is not None else 0.0 for n in miner_nodes]

    scores = []
    for node in miner_nodes:
        if node.avg_latency_ms is None:
            scores.append(0.0)
            continue
        relative = (max_latency - float(node.avg_latency_ms)) / (max_latency - min_latency)
        scores.append(float(min(max(relative, 0.0), 1.0)))
    return scores


def calculate_node_scores(miner_nodes: List[MinerNode]) -> List[NodeScore]:
    """
    Calculate node scores using weighted correctness, uptime, and latency.

    Correctness is a hard gate: if data verification fails, node score is 0.
    """
    if not miner_nodes:
        return []

    normalized_metric_weights = _normalize_weights(
        DEFAULT_METRIC_WEIGHTS,
        keys=["correctness", "uptime", "latency"],
    )

    latency_scores = _compute_latency_scores(miner_nodes)
    node_scores: List[NodeScore] = []

    for node, latency_score in zip(miner_nodes, latency_scores):
        correctness_score = 1.0 if node.data_verified else 0.0
        uptime_score = node.health.success_rate()
        if correctness_score <= 0.0:
            total_score = 0.0
        else:
            total_score = (
                normalized_metric_weights["correctness"] * correctness_score
                + normalized_metric_weights["uptime"] * uptime_score
                + normalized_metric_weights["latency"] * latency_score
            )

        node_scores.append(
            NodeScore(
                miner_hotkey=node.miner_hotkey,
                node_id=node.node_id,
                region=node.region,
                correctness=correctness_score,
                uptime=uptime_score,
                latency=latency_score,
                total=float(total_score),
            )
        )

    return node_scores


def calculate_miner_scores(node_scores: List[NodeScore]) -> List[MinerScore]:
    """
    Aggregate node scores to miner scores using regional multipliers,
    diminishing returns, and diversity bonus.

    Steps:
    1) Compute regional multipliers from node distribution:
       multiplier = clamp(target_share / actual_share, 0.5, 2.0)
    2) For each miner+region, sort node scores descending and apply diminishing:
       contribution = score_1/1 + score_2/2 + score_3/3 + ...
    3) Regional score = contribution * regional_multiplier
    4) Raw miner score = (sum regional scores) * diversity_bonus
    """
    if not node_scores:
        return []

    normalized_region_weights = _normalize_weights(
        DEFAULT_REGION_WEIGHTS,
        keys=list(SUPPORTED_REGIONS),
    )
    region_counts: Dict[str, int] = {region: 0 for region in SUPPORTED_REGIONS}
    for score in node_scores:
        if score.region in region_counts:
            region_counts[score.region] += 1

    total_nodes = sum(region_counts.values())
    region_multipliers: Dict[str, float] = {region: REGIONAL_MULTIPLIER_MAX for region in SUPPORTED_REGIONS}
    for region in SUPPORTED_REGIONS:
        count = region_counts[region]
        if count <= 0 or total_nodes <= 0:
            continue

        actual_share = count / total_nodes
        target_share = normalized_region_weights[region]
        raw_multiplier = target_share / actual_share
        region_multipliers[region] = float(
            min(
                REGIONAL_MULTIPLIER_MAX,
                max(REGIONAL_MULTIPLIER_MIN, raw_multiplier),
            )
        )

    # miner -> region -> [node scores]
    grouped_scores: Dict[str, Dict[str, List[float]]] = {}
    for score in node_scores:
        if score.region not in SUPPORTED_REGIONS:
            continue
        region_bucket = grouped_scores.setdefault(
            score.miner_hotkey,
            {region: [] for region in SUPPORTED_REGIONS},
        )
        region_bucket[score.region].append(score.total)

    miner_scores: List[MinerScore] = []
    for miner_hotkey, region_scores in grouped_scores.items():
        region_base_scores = {region: 0.0 for region in SUPPORTED_REGIONS}
        regional_totals = {region: 0.0 for region in SUPPORTED_REGIONS}

        for region in SUPPORTED_REGIONS:
            node_totals = sorted(region_scores[region], reverse=True)
            base = 0.0
            for index, node_score in enumerate(node_totals, start=1):
                base += node_score * (1.0 / index)
            region_base_scores[region] = float(base)
            regional_totals[region] = float(base * region_multipliers[region])

        regions_covered = sum(1 for region in SUPPORTED_REGIONS if region_scores[region])
        diversity_bonus = DIVERSITY_BONUS_BY_COVERAGE.get(
            regions_covered,
            DIVERSITY_BONUS_BY_COVERAGE[3],
        )
        total_score = sum(regional_totals.values()) * diversity_bonus

        miner_scores.append(
            MinerScore(
                miner_hotkey=miner_hotkey,
                regions=regional_totals,
                region_base_scores=region_base_scores,
                region_multipliers=region_multipliers.copy(),
                regions_covered=regions_covered,
                diversity_bonus=diversity_bonus,
                total=float(total_score),
            )
        )

    return miner_scores


def scores_to_weights(miner_scores: List[MinerScore], ordered_hotkeys: List[str]) -> np.ndarray:
    """
    Convert miner scores into pro-rata distribution weights.

    Args:
        miner_scores: Scores per miner.
        ordered_hotkeys: Ordered list of miner hotkeys to align with metagraph UIDs.
    """
    if not ordered_hotkeys:
        return np.array([], dtype=np.float32)

    by_hotkey = {score.miner_hotkey: score.total for score in miner_scores}
    raw_scores = np.array([float(by_hotkey.get(hotkey, 0.0)) for hotkey in ordered_hotkeys], dtype=np.float32)
    score_sum = float(raw_scores.sum())
    if score_sum <= 0:
        return np.zeros_like(raw_scores, dtype=np.float32)
    return raw_scores / score_sum
