# The MIT License (MIT)

import copy
import asyncio
import argparse
import threading
import bittensor as bt
import time
from typing import Union
from traceback import format_exception
import requests

__validator_version__ = "1.0.3"
version_split = __validator_version__.split(".")
__spec_version__ = (
    (1000 * int(version_split[0]))
    + (10 * int(version_split[1]))
    + (1 * int(version_split[2]))
)
weights_version_key = __spec_version__

def add_validator_args(cls, parser):
    parser.add_argument("--netuid", type=int, help="Subnet netuid", default=116)

    parser.add_argument(
        "--neuron.disable_set_weights",
        action="store_true",
        help="Disables setting weights.",
        default=False,
    )

    parser.add_argument(
        "--neuron.epoch_length",
        type=int,
        help="The default epoch length (how often we set weights, measured in 12 second blocks).",
        default=100,
    )

def config(cls):
    parser = argparse.ArgumentParser()
    (getattr(bt, "Wallet", None) or bt.wallet).add_args(parser)
    (getattr(bt, "Subtensor", None) or bt.subtensor).add_args(parser)
    (getattr(bt, "Axon", None) or bt.axon).add_args(parser)
    bt.logging.add_args(parser)
    cls.add_args(parser)
    return (getattr(bt, "Config", None) or bt.config)(parser)

class Validator():
    subtensor: None
    wallet: None
    metagraph: None

    @classmethod
    def config(cls):
        return config(cls)

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser):
        add_validator_args(cls, parser)

    def __init__(self, config=None):
        base_config = copy.deepcopy(config or self.config())
        self.config = self.config()
        self.config.merge(base_config)

        bt.logging.set_debug()

        # Log the configuration for reference.
        bt.logging.info(self.config)

        # Build Bittensor objects
        # These are core Bittensor classes to interact with the network.
        bt.logging.info("Setting up bittensor objects.")

        self.wallet = (getattr(bt, "Wallet", None) or bt.wallet)(config=self.config)
        self.subtensor = (getattr(bt, "Subtensor", None) or bt.subtensor)(config=self.config)
        self.metagraph = self.subtensor.metagraph(self.config.netuid)

        bt.logging.info(f"Wallet: {self.wallet}")
        bt.logging.info(f"Subtensor: {self.subtensor}")
        bt.logging.info(f"Metagraph: {self.metagraph}")

        # Check if the miner is registered on the Bittensor network before proceeding further.
        self.check_registered()

        # Each miner gets a unique identity (UID) in the network for differentiation.
        self.uid = self.metagraph.hotkeys.index(self.wallet.hotkey.ss58_address)
        bt.logging.info(
            f"Running neuron on subnet: {self.config.netuid} with uid {self.uid} using network: {self.subtensor.chain_endpoint}"
        )
        self.step = 0
        self.block = self.subtensor.get_current_block()

        # Instantiate runners
        self.should_exit: bool = False
        self.is_running: bool = False
        self.thread: Union[threading.Thread, None] = None

        # Init sync with the network. Updates the metagraph.
        self.sync()

        # Create asyncio event loop to manage async tasks.
        self.loop = asyncio.get_event_loop()

    def sync(self):
        self.block = self.subtensor.get_current_block()

        # Ensure miner or validator hotkey is still registered on the network.
        self.check_registered()

        if self.should_sync_metagraph():
            self.resync_metagraph()

        if self.should_set_weights():
            self.set_weights()

    def check_registered(self):
        # --- Check for registration.
        if not self.subtensor.is_hotkey_registered(
            netuid=self.config.netuid,
            hotkey_ss58=self.wallet.hotkey.ss58_address,
        ):
            bt.logging.error(
                f"Wallet: {self.wallet} is not registered on netuid {self.config.netuid}."
                f" Please register the hotkey using `btcli subnets register` before trying again"
            )
            exit()

    def should_sync_metagraph(self):
        return (
            self.block - self.metagraph.last_update[self.uid]
        ) > self.config.neuron.epoch_length

    def should_set_weights(self) -> bool:
        # Don't set weights on initialization.
        if self.step == 0:
            return False

        # Check if enough epoch blocks have elapsed since the last epoch.
        if self.config.neuron.disable_set_weights:
            return False

        # Define appropriate logic for when set weights.
        return (
            self.block - self.metagraph.last_update[self.uid]
        ) > self.config.neuron.epoch_length

    def run(self):
        # Check that validator is registered on the network.
        self.sync()

        bt.logging.info(f"Validator starting at block: {self.block}")

        try:
            while True:
                bt.logging.info(f"step({self.step}) block({self.block})")

                # Check if we should exit.
                if self.should_exit:
                    break

                # Sync metagraph and potentially set weights.
                self.sync()

                self.step += 1
                time.sleep(300)  # Sleep for 300 seconds.

        # If someone intentionally stops the validator, it'll safely terminate operations.
        except KeyboardInterrupt:
            self.axon.stop()
            bt.logging.success("Validator killed by keyboard interrupt.")
            exit()

        # In case of unforeseen errors, the validator will log the error and restart.
        except Exception as err:
            err_message = ''.join(format_exception(type(err), err, err.__traceback__))
            self.should_exit = True
            self.on_error(err, err_message)
        time.sleep(300)  # Sleep for 300 seconds.

    def on_error(self, error: Exception, error_message: str):
        bt.logging.error(f"Error during validation: {str(error)}")
        bt.logging.error(error_message)

    def run_in_background_thread(self):
        if not self.is_running:
            bt.logging.debug("Starting validator in background thread.")
            self.should_exit = False
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            self.is_running = True
            bt.logging.debug("Started")

    def stop_run_thread(self):
        if self.is_running:
            bt.logging.debug("Stopping validator in background thread.")
            self.should_exit = True
            self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

    def __enter__(self):
        self.run_in_background_thread()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.is_running:
            bt.logging.debug("Stopping validator in background thread.")
            self.should_exit = True
            self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

    def set_weights(self):
        bt.logging.info("set weights enter")

        url = "https://api.taolend.io/v1/weights"
        
        # Prepare headers with validator version and identity information
        headers = {
            "User-Agent": f"TaoLending-Validator/{__validator_version__}",
            "X-Validator-Version": __validator_version__,
            "X-Validator-Hotkey": self.wallet.hotkey.ss58_address,
            "X-Validator-UID": str(self.uid),
            "Content-Type": "application/json"
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            block_number = result.get("block_number")
            if block_number is None:
                bt.logging.info(f"Warning: Stale weights data from API. block_number={block_number}, current_block={self.block}")
                if self.block - self.metagraph.last_update[self.uid] < 300:
                    bt.logging.info(f"last_update={self.metagraph.last_update[self.uid]}, safe to skip set weight")
                    return
                uids = [0]
                weights = [1.0]
            else:
                created_at = result.get("created_at")
                weights_data = result.get("weights", {})
                uids = weights_data.get("uids", [0])
                weights = weights_data.get("weights", [1])
                bt.logging.info(f"Fetched weights: block_number={block_number}, created_at={created_at}, uids={uids}, weights={weights}")
        except Exception as e:
            bt.logging.error(f"Failed to fetch weights from API: {e}")
            uids = [0]
            weights = [1.0]

        if len(uids) == 0 or len(weights) == 0 or len(uids) != len(weights):
            if self.block - self.metagraph.last_update[self.uid] < 300:
                bt.logging.info(f"last_update={self.metagraph.last_update[self.uid]}, safe to skip set weight")
                return
            uids = [0]
            weights = [1.0]

        bt.logging.info(f"Setting weights on chain: uids={uids}, weights={weights}")
        # Set the weights on chain via our subtensor connection.
        result, msg = self.subtensor.set_weights(
            wallet=self.wallet,
            netuid=self.config.netuid,
            uids=uids,
            weights=weights,
            wait_for_finalization=True, # make potential issues visible
            wait_for_inclusion=False,
            version_key=weights_version_key
        )
        if result is True:
            bt.logging.info("set weights on chain successfully!")
        else:
            bt.logging.error("set weights failed", msg)

    def resync_metagraph(self):
        bt.logging.info("resync metagraph")

        # Sync the metagraph.
        self.metagraph.sync(subtensor=self.subtensor)

# The main function parses the configuration and runs the validator.
if __name__ == "__main__":
    with Validator() as validator:
        while not validator.should_exit:
            bt.logging.info(f"Validator running | uid {validator.uid} | step {validator.step} | {time.time()}")
            time.sleep(300)
