# The MIT License (MIT)
# Copyright © 2026 UnitOne Labs

import datetime
import os
from typing import Any, Optional

import bittensor as bt
import wandb

from flamewire.gateway.types import LatencyStats

WANDB_PROJECT = "FlameWire"
WANDB_ENTITY = "unitonelabs"


def get_run_id(uid: int, hotkey: str) -> str:
    """Generate stable run ID for validator (allows resume on restart)."""
    return f"validator-v2-{uid}-{hotkey}"


def init_wandb(config, hotkey: str, uid: int, netuid: int, **kwargs) -> Any:
    """Initialize wandb for validator logging."""
    run_id = get_run_id(uid, hotkey)

    offline_mode = getattr(config, "wandb", None) and getattr(config.wandb, "offline", False)
    mode = "offline" if offline_mode else "online"

    os.environ.setdefault("WANDB_INIT_TIMEOUT", "60")
    os.environ.setdefault("WANDB_SILENT", "true")

    api_key = os.getenv("WANDB_API_KEY")
    if not api_key:
        raise ValueError(
            "WANDB_API_KEY environment variable is required. "
            "Get your API key from https://wandb.ai/authorize"
        )

    bt.logging.debug("Logging in to wandb...")
    try:
        wandb.login(key=api_key, relogin=True)
        bt.logging.debug("wandb login successful")
    except Exception as e:
        raise RuntimeError(f"Failed to login to wandb: {e}")

    settings = wandb.Settings(console="off", _disable_stats=False)
    run_name = f"validator-{uid}-{hotkey[:8]}"

    notes = ""
    if getattr(config, "wandb", None) and hasattr(config.wandb, "notes"):
        notes = config.wandb.notes

    bt.logging.debug(f"Initializing wandb run: {run_id}")
    try:
        wandb.init(
            project=WANDB_PROJECT,
            entity=WANDB_ENTITY,
            id=run_id,
            resume="allow",
            mode=mode,
            name=run_name,
            notes=notes,
            settings=settings,
            config={
                "hotkey": hotkey,
                "uid": uid,
                "netuid": netuid,
                "ema_alpha": getattr(config.validator, "ema_alpha", 0.1),
                "max_workers": getattr(config.validator, "max_workers", 32),
                "epoch_length": getattr(config.neuron, "epoch_length", 360),
            },
            **kwargs
        )
    except Exception as e:
        raise RuntimeError(f"Failed to initialize wandb: {e}")

    bt.logging.info(f"wandb initialized in {mode} mode")
    bt.logging.info(f"wandb run ID: {run_id}")
    bt.logging.info(f"wandb project: {WANDB_ENTITY}/{WANDB_PROJECT}")

    wandb.define_metric("validator/step")
    wandb.define_metric("*", step_metric="validator/step")

    # Attach error tracking state to wandb instance
    wandb._error_rows = []
    wandb._error_count = 0

    return wandb


def log_verification_metrics(
    wandb_instance,
    step: int,
    block: int,
    verified_count: int,
    failed_count: int,
    total_nodes: int,
    total_miners: int,
    latency_stats: Optional[LatencyStats] = None,
):
    """Log verification metrics."""
    if wandb_instance is None:
        return

    metrics = {
        "validator/step": step,
        "validator/block": block,
        "verification/verified_count": verified_count,
        "verification/failed_count": failed_count,
        "verification/total_nodes": total_nodes,
        "verification/success_rate": verified_count / total_nodes if total_nodes > 0 else 0,
        "verification/total_miners": total_miners,
    }

    if latency_stats:
        metrics.update({
            "verification/latency_min_ms": latency_stats.min_ms,
            "verification/latency_max_ms": latency_stats.max_ms,
            "verification/latency_avg_ms": latency_stats.avg_ms,
        })

    try:
        wandb_instance.log(metrics)
        bt.logging.debug(f"Logged verification metrics: step={step}, verified={verified_count}")
    except Exception as e:
        bt.logging.error(f"Failed to log verification metrics: {e}")

def log_error(wandb_instance, error_type: str, message: str, step: Optional[int] = None):
    """Log error event to wandb."""
    if wandb_instance is None:
        return

    try:
        wandb_instance._error_count += 1
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Add to error history
        wandb_instance._error_rows.append([step or 0, timestamp, error_type, message])

        # Create fresh table with all errors so far
        table = wandb.Table(
            columns=["step", "timestamp", "error_type", "message"],
            data=wandb_instance._error_rows
        )

        # Log counter with step, but table separately without step
        if step is not None:
            wandb_instance.log({"validator/step": step, "errors/total": wandb_instance._error_count})

        # Log table separately (no step = always shows latest)
        wandb_instance.log({"errors/history": table})

        bt.logging.debug(f"Logged error to wandb: {error_type} (total: {wandb_instance._error_count})")
    except Exception as e:
        bt.logging.error(f"Failed to log error to wandb: {e}")


def log_status(wandb_instance, status: str, step: int):
    """Log validator status to wandb."""
    if wandb_instance is None:
        return

    try:
        wandb_instance.log({
            "validator/step": step,
            "validator/status": status,
        })
    except Exception as e:
        bt.logging.error(f"Failed to log status to wandb: {e}")


def finish_wandb(wandb_instance):
    """Finish wandb run."""
    if wandb_instance is None:
        return

    try:
        wandb_instance.finish()
        bt.logging.info("wandb run finished")
    except Exception as e:
        bt.logging.debug(f"Failed to finish wandb: {e}")
