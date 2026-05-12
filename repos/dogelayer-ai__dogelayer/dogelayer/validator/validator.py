#! /usr/bin/env python3

# Copyright © 2025 Latent Holdings
# Licensed under MIT

import argparse
import os
import traceback
import time
import sys
import logging as standard_logging  # 
import threading
import asyncio
import psutil
import subprocess
import platform
import re

from tabulate import tabulate

from bittensor import logging, Subtensor
import bittensor as bt
from bittensor_wallet.bittensor_wallet import Wallet
from dotenv import load_dotenv

from dogelayer.core.chain_data.pool_info import (
    publish_pool_info,
    get_pool_info,
    encode_pool_info,
)
from dogelayer.core.constants import (
    VERSION_KEY,
    U16_MAX,
    OWNER_TAKE,
    SPLIT_WITH_MINERS,
    PAYOUT_FACTOR,
)
from dogelayer.core.pool import Pool, PoolBase
from dogelayer.core.pool.metrics import ProxyMetrics, get_metrics_timerange
from dogelayer.core.pool.proxy import ProxyPool, ProxyPoolAPI
from dogelayer.core.pool.proxy.config import ProxyPoolAPIConfig, ProxyPoolConfig
from dogelayer.core.pool.pool_difficulty import get_pool_difficulty_with_fallback
from dogelayer.core.pricing import CoinPriceAPI
from dogelayer.core.pricing.network_stats import get_current_difficulty
from dogelayer.validator import BaseValidator


standard_logging.basicConfig(level=standard_logging.DEBUG, stream=sys.stdout)
standard_logging.getLogger('bittensor').setLevel(standard_logging.DEBUG)


COIN = "litecoin"

BAD_COLDKEYS = ["5CS96ckqKnd2snQ4rQKAvUpMh2pikRmCHb4H7TDzEt2AM9ZB"]


class DogeLayerProxyValidator(BaseValidator):
    """
    DogeLayer Proxy BTC Validator.
    """

    def __init__(self):
        super().__init__()
        self.is_subnet_owner = False
        self.pool = None
        self.pool_config = None
        self.api_config = None
        self.setup_bittensor_objects()
        self.price_api = CoinPriceAPI("coingecko", None)
        self.alpha = 0.8
        

        self.weights_interval = self.tempo
        

        if self.tempo < 50:
            self.eval_interval = max(self.config.eval_interval, self.tempo * 30)
            logging.info(f"⚠️ Detected small tempo({self.tempo}), using larger eval_interval to avoid frequent queries")
        
        logging.info(f"📊 IntervalConfiguration: tempo={self.tempo}, "
                    f"eval_interval={self.eval_interval}blocks({self.eval_interval*12/60:.1f}minutes), "
                    f"weights_interval={self.weights_interval}blocks({self.weights_interval*12/60:.1f}minutes)")
        
        self.config.coins = [COIN]
        self.last_evaluation_timestamp = None
        

        self.submit_to_db = os.getenv('SUBMIT_VALIDATOR_INFO', 'true').lower() == 'true'
        self.submit_interval = int(os.getenv('DB_SUBMIT_INTERVAL_SECONDS', '300'))
        self.last_submit_timestamp = None

    def add_args(self, parser: argparse.ArgumentParser):
        super().add_args(parser)
        ProxyPoolConfig.add_args(parser)
        ProxyPoolAPIConfig.add_args(parser)

    def setup_bittensor_objects(self):
        super().setup_bittensor_objects()
        self.burn_uid = self.get_burn_uid()
        self.burn_hotkey = self.get_burn_hotkey()
        self.is_subnet_owner = self.burn_hotkey == self.wallet.hotkey.ss58_address

        if self.is_subnet_owner:
            logging.info("SN owner detected - setting up pool configuration")
            try:
                self.pool_config = ProxyPoolConfig.from_args(self.config)
                self.api_config = ProxyPoolAPIConfig.from_args(self.config)
                self.pool = Pool(
                    pool_info=self.pool_config.to_pool_info(), config=self.api_config
                )
                self.publish_pool_info(
                    self.subtensor, self.config.netuid, self.wallet, self.pool
                )
                logging.info(
                    f"Pool configured with domain/IP: {self.pool.get_pool_info().domain}"
                )
            except Exception as e:
                logging.error(
                    f"Subnet owner must provide pool configuration via command line "
                    f"(--pool.domain, --pool.port) or environment variables "
                    f"(PROXY_DOMAIN, PROXY_PORT). Error: {e}"
                )
                exit(1)
        else:
            proxy_url = os.getenv("SUBNET_PROXY_API_URL")
            api_token = os.getenv("SUBNET_PROXY_API_TOKEN")

            if not proxy_url:
                raise ValueError(
                    "SUBNET_PROXY_API_URL environment variable must be set"
                )
            if not api_token:
                raise ValueError(
                    "SUBNET_PROXY_API_TOKEN environment variable must be set"
                )

            api = ProxyPoolAPI(proxy_url=proxy_url, api_token=api_token)
            self.pool = ProxyPool(pool_info=None, api=api)

    def _measure_network_latency(self, target_host: str = "8.8.8.8", timeout: int = 3) -> float:
        """Measure network latency by ping test"""
        backup_hosts = ["1.1.1.1", "8.8.4.4"] if target_host == "8.8.8.8" else ["8.8.8.8"]

        latency = self._ping_host(target_host, timeout)
        if latency > 0:
            return latency

        for backup_host in backup_hosts:
            latency = self._ping_host(backup_host, timeout)
            if latency > 0:
                logging.debug(f"Primary target {target_host} failed, using backup target {backup_host}")
                return latency
        
        return 0.0
    
    def _ping_host(self, target_host: str, timeout: int) -> float:
        """Execute ping command and return latency in milliseconds"""
        try:
            if platform.system().lower() == "windows":
                # Windows: ping -n 1 -w 3000 8.8.8.8
                cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), target_host]
            else:
                # Linux/Unix: ping -c 1 -W 3 8.8.8.8
                cmd = ["ping", "-c", "1", "-W", str(timeout), target_host]

            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=timeout + 1
            )
            
            if result.returncode == 0:
                output = result.stdout
                
                # ParsepingResultGetDelayTime
                if platform.system().lower() == "windows":
                    match = re.search(r'[Time=time=](\d+)ms', output, re.IGNORECASE)
                    if match:
                        return float(match.group(1))
                else:
                    match = re.search(r'time=(\d+\.?\d*).*ms', output)
                    if match:
                        return round(float(match.group(1)), 2)
            
            return 0.0
            
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, Exception) as e:
            logging.debug(f"ping {target_host} Failure: {e}")
            return 0.0

    def publish_pool_info(self, subtensor: "Subtensor", netuid: int, wallet: "Wallet", pool: PoolBase) -> None:
        pool_info = pool.get_pool_info()
        pool_info_bytes = encode_pool_info(pool_info)
        published_pool_info = get_pool_info(
            subtensor, netuid, wallet.hotkey.ss58_address)

        if published_pool_info is not None:
            logging.info("Pool info detected.")
            published_pool_info_bytes = encode_pool_info(published_pool_info)
            if published_pool_info_bytes == pool_info_bytes:
                logging.success("Pool info is already published.")
                return
            else:
                logging.info("Pool info is outdated.")

        logging.info("Publishing pool info to the chain.")
        success = publish_pool_info(subtensor, netuid, wallet, pool_info_bytes)
        if not success:
            logging.error("Failed to publish pool info")
            exit(1)
        else:
            logging.success("Pool info published successfully")

    def evaluate_miner_share_value(self) -> None:
        hotkey_to_uid = {hotkey: uid for uid,
                         hotkey in enumerate(self.hotkeys)}
        current_time = int(time.time())

        if self.last_evaluation_timestamp is None or self.last_evaluation_timestamp >= current_time:
            start_time = current_time - (10 * 60)
            logging.info(
                f"First evaluation or state recovery - using last 10 minutes for testing.")
        else:
            start_time = self.last_evaluation_timestamp

        end_time = current_time
        max_range = 24 * 60 * 60
        if end_time - start_time > max_range:
            start_time = end_time - max_range
            logging.warning(
                f"Time range capped to {max_range / 3600} hours to prevent large query.")

        logging.info(
            f"Attempting API call with start_time={start_time} and end_time={end_time}")

        try:
            for coin in self.config.coins:
                logging.info(f"Retrieving metrics for coin: {coin}")
                miner_metrics: list[ProxyMetrics] = get_metrics_timerange(
                    self.pool,
                    self.hotkeys,
                    self.block_at_registration,
                    start_time,
                    end_time,
                    coin,
                )

                if not miner_metrics:
                    logging.warning(
                        f"API returned an empty list of metrics for coin {coin}.")
                else:
                    logging.info(
                        f"API call successful. Received {len(miner_metrics)} miner metrics.")

                ltc_price = self.price_api.get_price(coin)
                if ltc_price is None or ltc_price == 0:
                    ltc_price = 75.0
                    logging.warning(
                        f"Price API failed for {coin}, using fallback price: ${ltc_price}")
                else:
                    logging.info(
                        f"Successfully fetched {coin} price: ${ltc_price}")

                ltc_difficulty = get_current_difficulty("litecoin")
                logging.info(
                    f"Successfully fetched network difficulty: {ltc_difficulty:,.0f} (using network difficulty for economic calculation)")

                for metric in miner_metrics:
                    if metric.hotkey not in hotkey_to_uid:
                        continue

                    uid = hotkey_to_uid[metric.hotkey]
                    share_value = metric.get_share_value_fiat(
                        ltc_price, ltc_difficulty)

                    if share_value > 0:
                        logging.info(
                            f"Share value: {share_value}, hotkey: {metric.hotkey}, uid: {uid}"
                        )
                    self.scores[uid] += share_value

                self._log_share_value_scores(coin, f"{end_time - start_time}s")

            self.last_evaluation_timestamp = current_time
            logging.info(
                f"Updated last_evaluation_timestamp to {current_time}")

        except Exception as e:
            logging.error(
                f"Failed to retrieve miner metrics for time range {start_time} to {end_time}: {e}. "
                f"Keeping last_evaluation_timestamp at {self.last_evaluation_timestamp}"
            )
            traceback.print_exc()

    def _log_share_value_scores(self, coin: str, timeframe: str) -> None:
        rows = []
        headers = ["UID", "Hotkey", "Score"]
        sorted_indices = sorted(range(len(self.scores)),
                                key=lambda s: self.scores[s], reverse=True)

        for i in sorted_indices:
            if self.scores[i] > 0:
                hotkey = self.metagraph.hotkeys[i]
                rows.append([i, f"{hotkey}", f"{self.scores[i]:.8f}"])

        if not rows:
            logging.info(
                f"No active miners for {coin} (timeframe: {timeframe}) at Block {self.current_block}")
            return

        table = tabulate(rows, headers=headers, tablefmt="grid",
                         numalign="right", stralign="left")
        title = f"Current Mining Scores - Block {self.current_block} - {coin.upper()} (Timeframe: {timeframe})"
        logging.info(f"Scores updated at block {self.current_block}")
        logging.info(f".\n{title}\n{table}")

    def save_state(self) -> None:
        state = {
            "scores": self.scores,
            "hotkeys": self.hotkeys,
            "block_at_registration": self.block_at_registration,
            "current_block": self.current_block,
            "last_evaluation_timestamp": self.last_evaluation_timestamp,
            
            "hotkey": self.wallet.hotkey.ss58_address if self.wallet and self.wallet.hotkey else "",
            "coldkey": self.wallet.coldkeypub.ss58_address if self.wallet and self.wallet.coldkeypub else "",
            "uid": self.uid if hasattr(self, 'uid') else 0,
            "netuid": self.config.netuid,
            "validator_stake": self.metagraph.total_stake[self.uid].tao if hasattr(self, 'metagraph') and hasattr(self, 'uid') and self.uid < len(self.metagraph.total_stake) else 0.0,
            "last_update": self.last_evaluation_timestamp,
            "version": "1.0.0",
            
        }

        logging.info("=== Validator State Details ===")
        logging.info(f"Block: {state['current_block']}")
        logging.info(f"UID: {state['uid']}")
        logging.info(f"Netuid: {state['netuid']}")
        logging.info(f"Hotkey: {state['hotkey'][:8]}...{state['hotkey'][-8:] if state['hotkey'] else 'N/A'}")
        logging.info(f"Coldkey: {state['coldkey'][:8]}...{state['coldkey'][-8:] if state['coldkey'] else 'N/A'}")
        logging.info(f"Validator Stake: {state['validator_stake']:.4f} TAO")
        logging.info(f"Scores Count: {len(state['scores']) if state['scores'] else 0}")
        logging.info(f"Hotkeys Count: {len(state['hotkeys']) if state['hotkeys'] else 0}")
        logging.info(f"Last Evaluation: {state['last_evaluation_timestamp']}")
        logging.info(f"Version: {state['version']}")
        logging.info("===============================")
        
        self.storage.save_state(state)
        logging.info(
            f"Saved validator state at block {self.current_block} with timestamp {self.last_evaluation_timestamp}")

    def restore_state_and_evaluate(self) -> None:
        state = self.storage.load_latest_state()
        if state is None:
            logging.info("No previous state found, starting fresh")
            return

        blocks_down = self.current_block - state["current_block"]
        if blocks_down >= (self.tempo * 1.5):
            logging.warning(
                f"Validator was down for {blocks_down} blocks (> {self.tempo * 1.5}). Starting fresh.")
            return

        total_hotkeys = len(state.get("hotkeys", []))
        self.scores = state.get("scores", [0.0] * total_hotkeys)
        self.hotkeys = state.get("hotkeys", [])
        self.block_at_registration = state.get("block_at_registration", [])
        self.last_evaluation_timestamp = state.get(
            "last_evaluation_timestamp", None)
        self.resync_metagraph()

        for idx in range(len(self.hotkeys)):
            if self.metagraph.coldkeys[idx] in BAD_COLDKEYS:
                self.scores[idx] = 0.0

        logging.warning(f"Validator was down for {blocks_down} blocks.")
        self.evaluate_miner_share_value()

        logging.success(
            f"Successfully restored validator state with last evaluation timestamp: {self.last_evaluation_timestamp}")

    def calculate_weights_distribution(self, total_value: float) -> list[float]:
        weights = [0.0] * len(self.hotkeys)
        tao_price = self.price_api.get_price("bittensor")
        subnet_price = self.subtensor.subnet(self.config.netuid).price.tao
        alpha_price = subnet_price * tao_price
        own_stake_weight = self.metagraph.total_stake[self.uid].tao
        total_stake = sum(self.metagraph.total_stake).tao
        blocks_to_set_for = self.current_block - self.last_update
        alpha_to_dist = (
            blocks_to_set_for
            * (1 - OWNER_TAKE)
            * SPLIT_WITH_MINERS
            * (own_stake_weight / total_stake)
        )
        value_to_dist = alpha_to_dist * alpha_price
        scaled_total_value = total_value * PAYOUT_FACTOR

        if scaled_total_value > value_to_dist:
            weights = [score / scaled_total_value for score in self.scores]
        else:
            weights_to_dist = scaled_total_value / value_to_dist
            weights = [(score / total_value) *
                       weights_to_dist for score in self.scores]

        remaining = max(0.0, 1.0 - sum(weights))
        if remaining > 0:
            weights[self.burn_uid] += remaining
        return weights

    def set_weights(self) -> tuple[bool, str]:
        total_value = sum(self.scores)
        if total_value == 0:
            logging.info("No miners are mining, we should burn the alpha")
            weights = [0.0] * len(self.hotkeys)
            weights[self.burn_uid] = 1.0
        else:
            weights = self.calculate_weights_distribution(total_value)

        # commit_reveal_enabled = self._get_commit_reveal_status()
        # logging.info(f"🎯 commit_reveal_weights_enabled: {commit_reveal_enabled}")

        # if commit_reveal_enabled:
        #     return self._set_weights_with_commit_reveal(weights)
        # else:
        #     return self._set_weights_direct(weights)

        return self._set_weights_direct(weights)

    def _set_weights_direct(self, weights: list[float]) -> tuple[bool, str]:
        """Submit weights directly to the chain"""
        logging.info("Using direct weight submission (commit-reveal disabled)")
        logging.info(
            "Attempting to send set_weights transaction to Subtensor...")

        success, err_msg = self.subtensor.set_weights(
            netuid=self.config.netuid,
            wallet=self.wallet,
            uids=list(range(len(self.hotkeys))),
            weights=weights,
            wait_for_inclusion=True,
            version_key=VERSION_KEY,
        )

        if success:
            logging.success("Successfully set weights on the chain.")
            self._log_weights_and_scores(weights)
            self.last_update = self.current_block
            self.scores = [0.0] * len(self.hotkeys)
            return True, err_msg
        else:
            logging.error(
                f"Failed to set weights. The transaction was not successful.")
            logging.error(f"Error from subtensor: {err_msg}")
            return False, err_msg

    def run(self):
        if self.config.state == "restore":
            self.restore_state_and_evaluate()
        else:
            self.resync_metagraph()

        logging.info(
            f"Starting validator loop, current block: {self.current_block}")
        self.ensure_validator_permit()
        next_sync_block = self.current_block + self.eval_interval
        logging.info(f"Next sync at block {next_sync_block}")

        while True:
            logging.debug(
                f"Entering main loop. Current block: {self.current_block}")

            try:
                if self.subtensor.wait_for_block(next_sync_block):
                    self.resync_metagraph()

                    self.evaluate_miner_share_value()

                    blocks_since_last_weights = self.subtensor.blocks_since_last_update(
                        self.config.netuid, self.uid
                    )
                    if self.submit_to_db:
                        current_time = int(time.time())
                        if (self.last_submit_timestamp is None or 
                            current_time - self.last_submit_timestamp >= self.submit_interval):
                            
                            logging.info(f"Scheduled submission of validator information to database")
                            try:
                                current_state = {
                                    "scores": self.scores,
                                    "hotkeys": self.hotkeys,
                                    "block_at_registration": self.block_at_registration,
                                    "current_block": self.current_block,
                                    "hotkey": self.wallet.hotkey.ss58_address if self.wallet and self.wallet.hotkey else "",
                                    "coldkey": self.wallet.coldkeypub.ss58_address if self.wallet and self.wallet.coldkeypub else "",
                                    "uid": self.uid if hasattr(self, 'uid') else 0,
                                    "netuid": self.config.netuid,
                                    "validator_stake": self.metagraph.total_stake[self.uid].tao if hasattr(self, 'metagraph') and hasattr(self, 'uid') and self.uid < len(self.metagraph.total_stake) else 0.0,
                                    "last_update": self.last_evaluation_timestamp,
                                    "version": "1.0.0",
                                    
                                    "cpu_usage": psutil.cpu_percent(interval=1),
                                    "memory_usage": psutil.virtual_memory().percent,
                                    "disk_usage": psutil.disk_usage('/').percent if hasattr(psutil, 'disk_usage') else 0.0,
                                    "network_latency": self._measure_network_latency(),
                                    "timestamp": current_time
                                }
                                
                                asyncio.run(self.storage._submit_validator_info(current_state))
                                self.last_submit_timestamp = current_time
                                logging.info(f"ValidatorInformationSubmitSuccess")
                            except Exception as e:
                                logging.error(f"❌ ValidatorInformationSubmitFailure: {e}")

                    if blocks_since_last_weights >= self.weights_interval:
                        success, err_msg = self.set_weights()
                        if not success:
                            logging.error(f"Failed to set weights: {err_msg}")
                            continue

                    self.save_state()
                    validator_trust = self.subtensor.query_subtensor(
                        "ValidatorTrust",
                        params=[self.config.netuid],
                    )
                    normalized_validator_trust = (
                        validator_trust[self.uid] / U16_MAX
                        if validator_trust[self.uid] > 0
                        else 0
                    )

                    next_sync_block, sync_reason = self.get_next_sync_block()
                    logging.info(
                        f"Block: {self.current_block} | "
                        f"Next sync: {next_sync_block} | "
                        f"Sync reason: {sync_reason} | "
                        f"VTrust: {normalized_validator_trust:.2f}"
                    )
                else:
                    logging.warning("Timeout waiting for block, retrying...")
                    continue

            except RuntimeError as e:
                logging.error(e)
                traceback.print_exc()

            except KeyboardInterrupt:
                logging.success(
                    "Keyboard interrupt detected. Exiting validator.")
                if hasattr(self, 'storage') and hasattr(self.storage, 'close'):
                    self.storage.close()
                exit()


def main():
    """Main entry point for the validator."""
    load_dotenv()
    logging.info("Validator script starting...")
    validator = DogeLayerProxyValidator()
    validator.run()


if __name__ == "__main__":
    main()
