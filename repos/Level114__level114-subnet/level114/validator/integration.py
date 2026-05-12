"""Helper utilities for integrating the validator runner."""

from __future__ import annotations

import asyncio

import bittensor as bt

from level114.api.collector_center_api import CollectorCenterAPI
from level114.validator.runner import Level114ValidatorRunner


async def integrate_scoring_system(validator_instance):
    """Attach the scoring runner to an existing validator instance."""
    collector_config = getattr(validator_instance.config, "collector", None)
    if not collector_config:
        bt.logging.error("No collector configuration found")
        return None

    collector_api = CollectorCenterAPI(
        base_url=collector_config.url,
        api_key=collector_config.api_key,
        timeout_seconds=getattr(collector_config, "timeout", 30.0),
    )

    runner = Level114ValidatorRunner(
        config=validator_instance.config,
        subtensor=validator_instance.subtensor,
        metagraph=validator_instance.metagraph,
        wallet=validator_instance.wallet,
        collector_api=collector_api,
    )

    validator_instance.scoring_runner = runner
    bt.logging.info("✅ Scoring system integrated successfully")
    return runner


async def enhanced_validator_loop(validator_instance):
    """Example loop that drives the scoring runner."""
    runner = await integrate_scoring_system(validator_instance)
    if runner is None:
        return

    try:
        while True:
            try:
                cycle_stats = await runner.run_scoring_cycle()
                mechanisms = cycle_stats.get("mechanisms", {})
                minecraft_stats = mechanisms.get(0, {})
                tcl_stats = mechanisms.get(1, {})

                bt.logging.info(
                    (
                        "Cycle {cycle} complete | Minecraft servers: {mc_processed} processed, "
                        "{mc_scores} scores | TCL metrics: {tcl_hotkeys} hotkeys | {duration:.1f}s"
                    ).format(
                        cycle=cycle_stats.get("cycle_id"),
                        mc_processed=minecraft_stats.get("servers_processed", 0),
                        mc_scores=minecraft_stats.get("scores_updated", 0),
                        tcl_hotkeys=tcl_stats.get("metrics_collected", 0),
                        duration=cycle_stats.get("total_time", 0.0),
                    )
                )

                cycle_interval = getattr(
                    validator_instance.config, "cycle_interval", 60
                )
                await asyncio.sleep(cycle_interval)

            except KeyboardInterrupt:
                bt.logging.info("Validator stopped by user")
                break
            except Exception as exc:  # noqa: BLE001
                bt.logging.error(f"Error in validator loop: {exc}")
                await asyncio.sleep(10)
    except Exception as exc:  # noqa: BLE001
        bt.logging.error(f"Fatal error in validator: {exc}")
        raise
