# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# UnitOne Labs: Alexander
# Copyright © 2026 UnitOne Labs

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


import copy
import asyncio
import argparse
import threading
import bittensor as bt
import numpy as np
import time

from typing import List, Union
from traceback import print_exception

from flamewire.base.neuron import BaseNeuron
from flamewire.utils.config import add_validator_args
from flamewire.utils.wandb_logging import init_wandb, finish_wandb, log_error, log_status


class BaseValidatorNeuron(BaseNeuron):
    """Base class for Bittensor validators."""

    neuron_type: str = "ValidatorNeuron"

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser):
        super().add_args(parser)
        add_validator_args(cls, parser)

    def __init__(self, config=None):
        super().__init__(config=config)

        # Initialize wandb logging if enabled in the config.
        self.wandb = init_wandb(
            self.config,
            hotkey=self.wallet.hotkey.ss58_address,
            uid=self.uid,
            netuid=self.config.netuid,
        )

        self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)

        # Initialize scores.
        self.scores = np.zeros(self.metagraph.n, dtype=np.float32)

        # Load state if exists.
        self.load_state()

        # Init sync with the network. Updates the metagraph.
        self.sync()

        # Create asyncio event loop to manage async tasks.
        self.loop = asyncio.get_event_loop()

        self.should_exit: bool = False
        self.is_running: bool = False
        self.thread: Union[threading.Thread, None] = None

        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()

    async def concurrent_verify(self):
        try:
            await self.verify()
        except Exception as e:
            bt.logging.error(f"Error in verify: {e}")
            log_error(self.wandb, "verify_error", str(e), step=self.step)

    def should_set_weights(self) -> bool:
        """
        Validators set weights explicitly after each completed verification cycle.
        """
        return False

    def run(self):
        self.sync()

        bt.logging.info(f"Validator starting at block: {self.block}")
        while True:
            try:
                start = time.time()
                bt.logging.info(f"step({self.step}) block({self.block})")
                log_status(self.wandb, "running", step=self.step)
                self.loop.run_until_complete(self.concurrent_verify())
                if self.should_exit:
                    break
                self.sync()
                self.step += 1
                elapsed = time.time() - start
                interval = getattr(self.config.validator, "verification_interval", 480)
                wait = max(interval - elapsed, 0)
                time.sleep(wait)
            except KeyboardInterrupt:
                bt.logging.success("Validator killed by keyboard interrupt.")
                exit()
            except Exception as err:
                bt.logging.error(f"Error during validation: {str(err)}")
                bt.logging.debug(str(print_exception(type(err), err, err.__traceback__)))
                log_error(self.wandb, "validation_error", str(err), step=self.step)

    def run_in_background_thread(self):
        """
        Starts the validator's operations in a background thread upon entering the context.
        This method facilitates the use of the validator in a 'with' statement.
        """
        if not self.is_running:
            bt.logging.debug("Starting validator in background thread.")
            self.should_exit = False
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            self.is_running = True
            bt.logging.debug("Started")

    def stop_run_thread(self):
        """
        Stops the validator's operations that are running in the background thread.
        """
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
        """
        Stops the validator's background operations upon exiting the context.
        This method facilitates the use of the validator in a 'with' statement.

        Args:
            exc_type: The type of the exception that caused the context to be exited.
                      None if the context was exited without an exception.
            exc_value: The instance of the exception that caused the context to be exited.
                       None if the context was exited without an exception.
            traceback: A traceback object encoding the stack trace.
                       None if the context was exited without an exception.
        """
        if self.is_running:
            bt.logging.debug("Stopping validator in background thread.")
            self.should_exit = True
            self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

        finish_wandb(self.wandb)

    def resync_metagraph(self):
        """Resyncs the metagraph and updates cached hotkeys and scores."""
        bt.logging.info("resync_metagraph()")

        # Copies state of metagraph before syncing.
        previous_metagraph = copy.deepcopy(self.metagraph)

        # Sync the metagraph.
        self.metagraph.sync(subtensor=self.subtensor)

        # Check if the metagraph axon info has changed.
        if previous_metagraph.axons == self.metagraph.axons:
            return

        bt.logging.info("Metagraph updated, re-syncing hotkeys and scores")

        # Zero out scores for replaced hotkeys.
        for uid, hotkey in enumerate(self.hotkeys):
            if hotkey != self.metagraph.hotkeys[uid]:
                self.scores[uid] = 0

        # Resize scores if metagraph size changed.
        if len(self.hotkeys) < len(self.metagraph.hotkeys):
            new_scores = np.zeros(self.metagraph.n, dtype=np.float32)
            min_len = min(len(self.hotkeys), len(self.scores))
            new_scores[:min_len] = self.scores[:min_len]
            self.scores = new_scores

        self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)

    def update_scores(self, rewards: np.ndarray, uids: List[int]):
        """Updates scores based on rewards."""
        # Check if rewards contains NaN values.
        if np.isnan(rewards).any():
            bt.logging.warning(f"NaN values detected in rewards: {rewards}")
            # Replace any NaN values in rewards with 0.
            rewards = np.nan_to_num(rewards, nan=0)

        # Ensure rewards is a numpy array with matching dtype.
        rewards = np.asarray(rewards, dtype=np.float32)

        # Check if `uids` is already a numpy array and copy it to avoid the warning.
        if isinstance(uids, np.ndarray):
            uids_array = uids.astype(np.int64, copy=True)
        else:
            uids_array = np.asarray(uids, dtype=np.int64)

        # Handle edge case: If either rewards or uids_array is empty.
        if rewards.size == 0 or uids_array.size == 0:
            bt.logging.warning("Either rewards or uids_array is empty. No updates will be performed.")
            return

        # Check if sizes of rewards and uids_array match.
        if rewards.size != uids_array.size:
            raise ValueError(
                f"Shape mismatch: rewards array of shape {rewards.shape} "
                f"cannot be broadcast to uids array of shape {uids_array.shape}"
            )

        # Update the tracked scores in-place.
        self.scores[uids_array] = rewards
        bt.logging.debug(f"Updated scores for uids={uids_array.tolist()}")

    def set_weights(self):
        """Sets weights on chain."""
        if self.config.neuron.disable_set_weights:
            return

        weights = self.scores / (self.scores.sum() + 1e-8)
        uids = np.arange(len(weights))

        bt.logging.info(f"Setting weights for {len(uids)} uids")
        result, msg = self.subtensor.set_weights(
            wallet=self.wallet,
            netuid=self.config.netuid,
            uids=uids,
            weights=weights,
            wait_for_inclusion=False,
            version_key=self.spec_version,
        )
        if result:
            bt.logging.info(f"set_weights success: {msg}")
        else:
            bt.logging.error(f"set_weights failed: {msg}")

    def save_state(self):
        """Saves scores to file."""
        path = f"{self.config.neuron.full_path}/scores.npy"
        np.save(path, self.scores)
        bt.logging.debug(f"Saved scores to {path}")

    def load_state(self):
        """Loads scores from file."""
        path = f"{self.config.neuron.full_path}/scores.npy"
        try:
            self.scores = np.load(path)
            bt.logging.info(f"Loaded scores from {path}")
        except FileNotFoundError:
            bt.logging.info("No saved scores found, starting fresh")

    def _sync_loop(self):
        interval = 60
        while not self.should_exit:
            time.sleep(interval)
            bt.logging.debug(f"Periodic sync (interval={interval}s)")
            self.sync()
