from __future__ import annotations

import time
import math
from typing import Any, Dict, Optional

import bittensor as bt

from level114.api.collector_center_api import CollectorCenterAPI
from level114.validator.mechanisms import (
    MechanismContext,
    MinecraftMechanism,
    ScoreCacheEntry,
    TclMechanism,
    ValidatorMechanism,
)
from level114.validator.weights import WeightState, apply_weight_updates


class Level114ValidatorRunner:
    """Main validator runner coordinating multiple mechanisms."""

    def __init__(
        self,
        config: Any,
        subtensor: Any,
        metagraph: Any,
        wallet: Any,
        collector_api: CollectorCenterAPI,
    ) -> None:
        self.config = config
        self.subtensor = subtensor
        self.metagraph = metagraph
        self.wallet = wallet
        self.collector_api = collector_api

        self._mechanism_registry: Dict[int, type[ValidatorMechanism]] = {
            MinecraftMechanism.mechanism_id: MinecraftMechanism,
            TclMechanism.mechanism_id: TclMechanism,
        }
        enabled_ids = sorted(self._mechanism_registry.keys())
        context = MechanismContext(
            config=self.config,
            subtensor=self.subtensor,
            metagraph=self.metagraph,
            wallet=self.wallet,
            collector_api=self.collector_api,
        )

        self._mechanisms: Dict[int, ValidatorMechanism] = {}
        for mechanism_id in enabled_ids:
            mechanism_cls = self._mechanism_registry.get(mechanism_id)
            if mechanism_cls is None:
                bt.logging.warning(
                    f"Requested validator mechanism {mechanism_id} is not available; skipping"
                )
                continue
            self._mechanisms[mechanism_id] = mechanism_cls(context)

        if not self._mechanisms:
            raise ValueError("No validator mechanisms enabled")

        mechanism_summary = ", ".join(
            f"{mid}:{mech.mechanism_name}"
            for mid, mech in sorted(self._mechanisms.items())
        )
        bt.logging.info(
            f"Level114 Validator Runner initialized with mechanisms: {mechanism_summary}"
        )

        self._global_cycle_count = 0
        validator_cfg = getattr(self.config, "validator", None)
        configured_update_interval = self._coerce_interval(
            getattr(validator_cfg, "weight_update_interval", None) if validator_cfg else None,
            1200.0,
        )
        self.weight_update_interval = 20.0 * 60.0
        if configured_update_interval != self.weight_update_interval:
            bt.logging.info(
                "Weight update interval overridden to 1200s (20 minutes) per policy"
            )
        self.weight_retry_interval = max(
            self._coerce_interval(
                getattr(validator_cfg, "weight_retry_interval", None) if validator_cfg else None,
                60.0,
            ),
            10.0,
        )
        self._weight_states: Dict[int, WeightState] = {
            mechanism_id: WeightState()
            for mechanism_id in self._mechanisms.keys()
        }

    @property
    def cycle_count(self) -> int:
        return self._global_cycle_count

    async def run_scoring_cycle(self) -> Dict[str, Any]:
        """Run one complete scoring cycle across all enabled mechanisms."""
        cycle_start = time.time()
        mechanism_results: Dict[int, Dict[str, Any]] = {}

        for mechanism_id, mechanism in self._mechanisms.items():
            stats = await mechanism.run_cycle()
            mechanism_results[mechanism_id] = stats

        weights_updated = apply_weight_updates(
            states=self._weight_states,
            mechanism_results=mechanism_results,
            metagraph=self.metagraph,
            subtensor=self.subtensor,
            wallet=self.wallet,
            netuid=self.config.netuid,
            update_interval=self.weight_update_interval,
            retry_interval=self.weight_retry_interval,
        )

        self._global_cycle_count += 1
        total_time = time.time() - cycle_start

        aggregate_errors = sum(
            stats.get("errors", 0) for stats in mechanism_results.values()
        )

        return {
            "cycle_id": self._global_cycle_count,
            "timestamp": cycle_start,
            "total_time": total_time,
            "mechanisms": mechanism_results,
            "weights_updated": weights_updated,
            "errors": aggregate_errors,
        }

    def get_status(self) -> Dict[str, Any]:
        mechanism_status: Dict[int, Dict[str, Any]] = {}
        for mechanism_id, mechanism in self._mechanisms.items():
            info = dict(mechanism.get_status())
            state = self._weight_states.get(mechanism_id)
            if state:
                info["last_weights_update"] = state.last_update
                info["next_weight_update"] = state.next_update
                info["last_weight_attempt"] = state.last_attempt
            mechanism_status[mechanism_id] = info

        primary = mechanism_status.get(MinecraftMechanism.mechanism_id)
        if primary is None and mechanism_status:
            primary = next(iter(mechanism_status.values()))
        multi = len(self._mechanisms) > 1

        status: Dict[str, Any] = {
            "cycle_count": self._global_cycle_count,
            "mechanism_id": "multi" if multi else primary.get("mechanism_id") if primary else None,
            "mechanism_name": "multi" if multi else primary.get("mechanism_name") if primary else None,
            "mechanisms": mechanism_status,
            "last_weights_update": primary.get("last_weights_update") if primary else None,
            "next_weight_update": primary.get("next_weight_update") if primary else None,
            "last_weight_attempt": primary.get("last_weight_attempt") if primary else None,
            "cached_scores": primary.get("cached_scores") if primary else None,
            "cached_mappings": primary.get("cached_mappings") if primary else None,
            "replay_protection_active": primary.get("replay_protection_active") if primary else None,
        }

        config_snapshot = dict(primary.get("config", {}) if primary else {})
        config_snapshot.setdefault("weight_update_interval", self.weight_update_interval)
        config_snapshot.setdefault("weight_retry_interval", self.weight_retry_interval)
        status["config"] = config_snapshot

        tcl_status = mechanism_status.get(TclMechanism.mechanism_id, {})
        if tcl_status:
            status["metrics_cached"] = tcl_status.get("metrics_cached")
            status["last_metrics_timestamp"] = tcl_status.get("last_metrics_timestamp")

        return status

    def get_server_id_for_hotkey(self, hotkey: str) -> Optional[str]:
        mechanism = self._mechanisms.get(MinecraftMechanism.mechanism_id)
        if mechanism is None:
            return None
        return mechanism.get_server_id_for_hotkey(hotkey)

    def get_cached_score(self, server_id: str) -> Optional[ScoreCacheEntry]:
        mechanism = self._mechanisms.get(MinecraftMechanism.mechanism_id)
        if mechanism is None:
            return None
        return mechanism.get_cached_score(server_id)

    @staticmethod
    def _coerce_interval(value: Optional[Any], fallback: float) -> float:
        try:
            if value is None:
                raise ValueError
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError
            return numeric
        except (TypeError, ValueError):
            return float(fallback)
