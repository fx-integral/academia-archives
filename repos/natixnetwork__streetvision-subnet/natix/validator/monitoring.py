import threading

import bittensor as bt
import wandb
import yaml

import natix
from natix.validator.config import (
    MAINNET_UID,
    MAINNET_WANDB_PROJECT,
    TESTNET_WANDB_PROJECT,
    VALIDATOR_INFO_PATH,
    WANDB_ENTITY,
)


def init_wandb(validator) -> None:
    """Initialise a W&B run on the validator and schedule auto-restarts."""
    if validator.config.wandb.off:
        return

    def _start_run():
        if validator.wandb_run:
            try:
                validator.wandb_run.finish()
                bt.logging.info("Finished previous wandb run")
            except Exception as err:
                bt.logging.warning(f"Failed to finish existing W&B run: {err}")

        run_name = f"validator-{validator.uid}-{natix.__version__}"
        validator.config.run_name = run_name
        validator.config.uid = validator.uid
        validator.config.hotkey = validator.wallet.hotkey.ss58_address
        validator.config.version = natix.__version__
        validator.config.type = validator.neuron_type

        wandb_project = MAINNET_WANDB_PROJECT if validator.config.netuid == MAINNET_UID else TESTNET_WANDB_PROJECT
        bt.logging.info(f"Initializing W&B run for '{WANDB_ENTITY}/{wandb_project}'")

        try:
            validator.wandb_run = wandb.init(
                name=run_name,
                project=wandb_project,
                entity=WANDB_ENTITY,
                config=validator.config,
                resume="auto",
                tags=[validator.config.neuron.name],
                dir=validator.config.full_path,
                reinit=True,
            )
        except wandb.UsageError as e:
            bt.logging.warning(e)
            bt.logging.warning("Did you run wandb login?")
            validator.wandb_run = None
            return

        signature = validator.wallet.hotkey.sign(validator.wandb_run.id.encode()).hex()
        validator.config.signature = signature
        wandb.config.update(validator.config, allow_val_change=True)
        bt.logging.success(f"Started wandb run {run_name}")

        if validator.config.wandb.restart_interval > 0:
            if validator.wandb_restart_timer:
                validator.wandb_restart_timer.cancel()
            validator.wandb_restart_timer = threading.Timer(
                validator.config.wandb.restart_interval * 3600,
                _start_run,
            )
            validator.wandb_restart_timer.daemon = True
            validator.wandb_restart_timer.start()
            bt.logging.info(f"W&B auto-restart scheduled in {validator.config.wandb.restart_interval} hours.")

    _start_run()


def store_vali_info(validator) -> None:
    """Write validator identity to disk so background processes can read it."""
    info = {
        "uid": validator.uid,
        "hotkey": validator.wallet.hotkey.ss58_address,
        "netuid": validator.config.netuid,
        "full_path": validator.config.neuron.full_path,
    }
    with open(VALIDATOR_INFO_PATH, "w") as f:
        yaml.safe_dump(info, f, indent=4)
    bt.logging.info(f"Wrote validator info to {VALIDATOR_INFO_PATH}")


def cleanup_wandb(validator) -> None:
    """Cancel the auto-restart timer and finish the W&B run on shutdown."""
    if validator.wandb_restart_timer:
        try:
            validator.wandb_restart_timer.cancel()
            bt.logging.info("Cancelled W&B restart timer")
        except Exception as e:
            bt.logging.warning(f"Error cancelling W&B restart timer: {e}")

    if validator.wandb_run:
        try:
            validator.wandb_run.finish()
            bt.logging.info("Finished W&B run on shutdown")
        except Exception as e:
            bt.logging.warning(f"Error finishing W&B run on shutdown: {e}")
