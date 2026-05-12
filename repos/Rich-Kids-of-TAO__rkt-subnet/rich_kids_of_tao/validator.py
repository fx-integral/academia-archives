import time
import asyncio
import argparse
import numpy as np
import bittensor as bt
from typing import Optional

from .emission_checker import (
    check_metagraph_emissions,
    process_emissions_and_rewards,
    fetch_subnet_weights_from_api,
)


class RichKidsValidator:
    def __init__(self, config: Optional[bt.config] = None):
        self.config = config or bt.config()
        if not hasattr(self.config, "netuid"):
            raise ValueError("netuid must be specified in config")

        bt.logging.set_debug(True)
        bt.logging.set_trace(True)

        self.wallet = bt.wallet(config=self.config)
        self.subtensor = bt.subtensor(config=self.config)
        self.metagraph = self.subtensor.metagraph(self.config.netuid)

        self.scores = np.zeros(self.metagraph.n, dtype=np.float32)

        self.burner_uid = 0
        self.burner_weight = 0.9
        self.moving_average_alpha = 0.1
        self.evaluation_sleep = 1800
        self.epoch_length = 360

        # Fetch subnet weights from API (fallback to hardcoded if API fails)
        self.subnets_to_check = fetch_subnet_weights_from_api()

        self.subnet_prices = self.fetch_all_subnet_prices()
        self.subnet_metagraphs = self.fetch_all_subnet_metagraphs()

    @staticmethod
    def add_args(parser: argparse.ArgumentParser):
        parser.add_argument("--netuid", type=int, required=True)
        parser.add_argument("--subtensor.network", type=str, default="finney")
        parser.add_argument("--wallet.name", type=str, required=True)
        parser.add_argument("--wallet.hotkey", type=str, required=True)
        parser.add_argument("--logging.debug", action="store_true")

    def sync_metagraph(self):
        self.metagraph.sync(subtensor=self.subtensor)
        bt.logging.info(f"Synced metagraph: {self.metagraph.n} neurons")
        bt.logging.debug(
            f"Last update after sync: {self.metagraph.last_update[self.get_uid()]}"
        )

    def update_scores(self, rewards, uids):
        scattered_rewards = np.zeros_like(self.scores)
        uids_array = np.array(uids)
        rewards_array = np.array(rewards)

        scattered_rewards[uids_array] = rewards_array

        self.scores = (
            self.moving_average_alpha * scattered_rewards
            + (1 - self.moving_average_alpha) * self.scores
        )

        bt.logging.info(f"Updated EMA scores: {[f'{s:.6f}' for s in self.scores]}")

    def set_weights(self):
        try:
            uids = list(range(len(self.scores)))
            raw_weights = self.scores.tolist()

            if self.burner_uid not in uids:
                uids.insert(0, self.burner_uid)
                raw_weights.insert(0, 0.0)

            weights = self._calculate_weights_with_burner(uids, raw_weights)

            bt.logging.info(
                f"Setting weights - Weights: {[f'{w:.6f}' for w in weights]}"
            )

            result = self.subtensor.set_weights(
                wallet=self.wallet,
                netuid=self.config.netuid,
                uids=uids,
                weights=weights,
                wait_for_inclusion=False,
            )

            if result:
                bt.logging.success("Successfully set weights")
                bt.logging.info("Syncing metagraph after weight setting...")
                self.sync_metagraph()
                bt.logging.debug(f"Result: {result}")
            else:
                bt.logging.error("Failed to set weights")
                bt.logging.debug(f"Result: {result}")

            return result
        except Exception as e:
            bt.logging.error(f"Error setting weights: {e}")
            return False

    def _calculate_weights_with_burner(self, uids, scores):
        remaining_weight = 1.0 - self.burner_weight

        total_other_scores = sum(
            score for uid, score in zip(uids, scores) if uid != self.burner_uid
        )

        weights = []
        for uid, score in zip(uids, scores):
            if uid == self.burner_uid:
                weights.append(self.burner_weight)
            elif total_other_scores > 0:
                weights.append((score / total_other_scores) * remaining_weight)
            else:
                weights.append(0.0)

        return weights

    def fetch_all_subnet_prices(self):
        bt.logging.info(
            f"Fetching prices for subnets: {list(self.subnets_to_check.keys())}"
        )
        subnet_prices = {}

        try:
            for netuid in self.subnets_to_check.keys():
                try:
                    price = self.subtensor.get_subnet_price(netuid=netuid)
                    subnet_prices[netuid] = price.tao
                    bt.logging.info(f"Netuid {netuid}: price = {price.tao:.4f} TAO")
                except Exception as e:
                    bt.logging.warning(f"Could not get price for netuid {netuid}: {e}")
                    subnet_prices[netuid] = 1.0

            bt.logging.info(f"Fetched prices for {len(subnet_prices)} subnets")
            return subnet_prices
        except Exception as e:
            bt.logging.error(f"Failed to fetch subnet prices: {e}")
            return {}

    def fetch_all_subnet_metagraphs(self):
        bt.logging.info(
            f"Fetching metagraphs for subnets: {list(self.subnets_to_check.keys())}"
        )
        subnet_metagraphs = {}

        try:
            for netuid in self.subnets_to_check.keys():
                try:
                    metagraph = self.subtensor.metagraph(netuid)
                    subnet_metagraphs[netuid] = metagraph
                    bt.logging.info(
                        f"Netuid {netuid}: metagraph loaded ({metagraph.n} neurons)"
                    )
                except Exception as e:
                    bt.logging.warning(
                        f"Could not get metagraph for netuid {netuid}: {e}"
                    )

            bt.logging.info(f"Fetched metagraphs for {len(subnet_metagraphs)} subnets")
            return subnet_metagraphs
        except Exception as e:
            bt.logging.error(f"Failed to fetch subnet metagraphs: {e}")
            return {}

    def sync_subnet_metagraphs(self):
        bt.logging.info("Syncing subnet metagraphs...")
        for netuid in self.subnets_to_check.keys():
            if netuid in self.subnet_metagraphs:
                try:
                    self.subnet_metagraphs[netuid].sync(subtensor=self.subtensor)
                    bt.logging.debug(f"Synced metagraph for netuid {netuid}")
                except Exception as e:
                    bt.logging.warning(
                        f"Could not sync metagraph for netuid {netuid}: {e}"
                    )
        bt.logging.info("Subnet metagraphs synced")

    def should_set_weights(self) -> bool:
        current_block = self.subtensor.get_current_block()
        uid = self.get_uid()
        blocks_since_last_update = current_block - self.metagraph.last_update[uid]

        bt.logging.info(
            f"Weight check - Current block: {current_block}, Last update: {self.metagraph.last_update[uid]}, Blocks since: {blocks_since_last_update}, Epoch length: {self.epoch_length}"
        )

        should_set = blocks_since_last_update >= self.epoch_length
        bt.logging.info(f"Should set weights: {should_set}")

        return should_set

    def get_uid(self):
        try:
            return self.metagraph.hotkeys.index(self.wallet.hotkey.ss58_address)
        except ValueError:
            bt.logging.error(
                f"Validator hotkey {self.wallet.hotkey.ss58_address} not found in metagraph"
            )
            return 0

    async def evaluate_miners(self):
        bt.logging.info("=== Miner Appreciation Evaluation Starting ===")

        bt.logging.info("Syncing subnet metagraphs...")
        self.sync_subnet_metagraphs()

        bt.logging.info(
            f"Checking metagraph with {len(self.metagraph.hotkeys)} total hotkeys"
        )

        all_miner_uids, miner_emissions = check_metagraph_emissions(self)

        bt.logging.info(f"Found {len(all_miner_uids)} miners to check")

        if not all_miner_uids:
            bt.logging.info("No miners found, sleeping 30s")
            time.sleep(30)
            return

        emission_values, rewards = process_emissions_and_rewards(
            all_miner_uids, miner_emissions
        )

        if len(rewards) > 0:
            bt.logging.info(f"Setting scores for {len(rewards)} miners")
            self.update_scores(rewards, all_miner_uids)
        else:
            bt.logging.warning("No rewards calculated")

        should_set = self.should_set_weights()
        if should_set:
            bt.logging.info("Setting weights now...")
            self.set_weights()
        else:
            bt.logging.info("Not setting weights this round")

        bt.logging.info("=== Evaluation Complete ===")

    def run(self):
        while True:
            current_block = self.subtensor.get_current_block()
            bt.logging.info(f"Validator running at block {current_block}...")
            try:
                self.sync_metagraph()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.evaluate_miners())
                loop.close()
            except Exception as e:
                bt.logging.error(f"Evaluation failed: {e}")

            bt.logging.info(f"Sleeping {self.evaluation_sleep}s...")
            time.sleep(self.evaluation_sleep)


def main():
    parser = argparse.ArgumentParser()
    RichKidsValidator.add_args(parser)
    config = bt.config(parser)

    validator = RichKidsValidator(config)
    validator.run()


if __name__ == "__main__":
    main()
