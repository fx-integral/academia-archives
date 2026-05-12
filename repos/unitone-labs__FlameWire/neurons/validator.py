# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
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

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import time
import bittensor as bt
import numpy as np

from flamewire.base.validator import BaseValidatorNeuron
from flamewire.gateway import GatewayClient, RpcClient, SubtensorRpcTransport
from flamewire.gateway.types import CheckStats, LatencyStats
from flamewire.utils.metagraph import get_miner_hotkeys
from flamewire.utils.helpers import batched, build_miner_nodes, get_random_blocks, verify_all_nodes
from flamewire.utils.scoring import calculate_node_scores, calculate_miner_scores
from flamewire.utils.wandb_logging import log_verification_metrics


def apply_reward_ema(
    rewards: np.ndarray,
    uids: np.ndarray,
    previous_scores: np.ndarray,
    ema_alpha: float,
    ema_initialized_uids: set[int],
    active_uids: set[int],
) -> tuple[np.ndarray, set[int]]:
    """
    Apply EMA smoothing only for active miners.

    Miners with no active nodes this cycle are zeroed immediately so stale scores
    do not linger after node wipeouts.
    """
    smoothed = rewards.astype(np.float32, copy=True)
    updated_initialized = set(ema_initialized_uids)

    for idx, uid in enumerate(uids):
        uid_int = int(uid)

        if uid_int not in active_uids:
            smoothed[idx] = 0.0
            updated_initialized.discard(uid_int)
            continue

        if uid_int in updated_initialized:
            smoothed[idx] = (
                ((1.0 - ema_alpha) * float(previous_scores[idx]))
                + (ema_alpha * float(rewards[idx]))
            )

        updated_initialized.add(uid_int)

    return smoothed, updated_initialized


class Validator(BaseValidatorNeuron):
    def __init__(self, config=None):
        # Local health history measured by this validator only (node_id -> CheckStats).
        self.local_node_health: dict[str, CheckStats] = {}
        # Tracks which miner UIDs already have EMA initialized.
        self.ema_initialized_uids: set[int] = set()

        super(Validator, self).__init__(config=config)

        # Initialize gateway client
        self.gateway = GatewayClient(
            api_key=self.config.validator.api_key,
            base_url=self.config.gateway.url,
        )
        bt.logging.info(f"Gateway client initialized: {self.config.gateway.url}")

        # Initialize reference RPC client from validator-controlled endpoint.
        reference_rpc_url = (
            getattr(self.config.validator, "reference_rpc_url", "")
            or self.config.subtensor.network
        )
        self.rpc = RpcClient(SubtensorRpcTransport(reference_rpc_url))
        bt.logging.info(f"Reference RPC initialized: {reference_rpc_url}")

    def _node_health_path(self) -> str:
        return f"{self.config.neuron.full_path}/node_health_stats.json"

    def load_state(self):
        super().load_state()
        path = self._node_health_path()
        try:
            with open(path) as f:
                raw = json.load(f)

            # Backward compatibility with older flat schema.
            if "node_health" in raw:
                node_health_raw = raw.get("node_health", {})
                ema_uids_raw = raw.get("ema_initialized_uids", [])
            else:
                node_health_raw = raw
                ema_uids_raw = []

            self.local_node_health = {
                node_id: CheckStats(
                    total=int(stats.get("total", 0)),
                    passed=int(stats.get("passed", 0)),
                )
                for node_id, stats in node_health_raw.items()
            }
            self.ema_initialized_uids = {
                int(uid)
                for uid in ema_uids_raw
            }
            bt.logging.info(f"Loaded local node health from {path}")
        except FileNotFoundError:
            bt.logging.info("No local node health state found, starting fresh")
        except Exception as err:
            bt.logging.warning(f"Failed to load local node health state: {err}")
            self.local_node_health = {}
            self.ema_initialized_uids = set()

    def save_state(self):
        super().save_state()
        path = self._node_health_path()
        try:
            payload = {
                "node_health": {
                    node_id: {"total": stats.total, "passed": stats.passed}
                    for node_id, stats in self.local_node_health.items()
                },
                "ema_initialized_uids": sorted(list(self.ema_initialized_uids)),
            }
            with open(path, "w") as f:
                json.dump(payload, f)
            bt.logging.debug(f"Saved local node health to {path}")
        except Exception as err:
            bt.logging.warning(f"Failed to save local node health state: {err}")

    def _merge_local_health(self, miner_nodes):
        """Merge cycle health checks into persistent validator-local uptime history."""
        for node in miner_nodes:
            cycle = node.health
            previous = self.local_node_health.get(node.node_id, CheckStats(total=0, passed=0))
            merged = CheckStats(
                total=previous.total + cycle.total,
                passed=previous.passed + cycle.passed,
            )
            self.local_node_health[node.node_id] = merged
            # Use cumulative local stats for uptime scoring.
            node.health = merged

    async def verify(self):
        """Lookup nodes for all miners and verify them."""
        miner_hotkeys = get_miner_hotkeys(self.metagraph, self.uid)
        if not miner_hotkeys:
            return

        # Lookup nodes for all miners
        all_nodes = {}
        for batch in batched(miner_hotkeys, 100):
            nodes = self.gateway.lookup_nodes(batch)
            all_nodes.update(nodes)

        # Build MinerNode array with validator-local health placeholders.
        miner_nodes = build_miner_nodes(all_nodes)

        # Get current block
        current_block = self.rpc.get_current_block()
        bt.logging.info(f"Current block: {current_block}")

        # Get random blocks from each interval
        old_block, middle_block, new_block = get_random_blocks(current_block)
        bt.logging.info(f"Random blocks - old: {old_block}, middle: {middle_block}, new: {new_block}")

        # Fetch reference blocks
        reference_blocks = []
        for block_num, verification_type in [
            (old_block, "old"),
            (middle_block, "middle"),
            (new_block, "new"),
        ]:
            ref_block = self.rpc.get_reference_block(block_num, verification_type)
            if ref_block:
                reference_blocks.append(ref_block)
                bt.logging.info(f"Reference block {verification_type}: #{ref_block.block_number} hash={ref_block.block_hash[:16]}... size={ref_block.events_data_size}")

        if not reference_blocks:
            bt.logging.error(
                "No reference blocks available from reference RPC endpoint. "
                "Check REFERENCE_RPC_URL and ensure it is archive-capable."
            )
            return

        # Verify all miner nodes against reference blocks (parallel)
        bt.logging.info(f"Verifying {len(miner_nodes)} nodes against {len(reference_blocks)} reference blocks (max_workers={self.config.validator.max_workers})...")
        verified_count, failed_count = verify_all_nodes(
            miner_nodes,
            reference_blocks,
            self.gateway.rpc_call,
            network_head=current_block,
            max_workers=self.config.validator.max_workers,
        )
        bt.logging.info(f"Verification complete: {verified_count} passed, {failed_count} failed")

        # Hotkeys with at least one node that passed data verification this cycle.
        verified_hotkeys = {
            node.miner_hotkey for node in miner_nodes if node.data_verified
        }
        bt.logging.info(f"Miners with verified nodes: {len(verified_hotkeys)}")

        # Merge cycle measurements into validator-local uptime history.
        self._merge_local_health(miner_nodes)

        # Calculate performance scores using subnet-level scoring policy constants.
        node_scores = calculate_node_scores(miner_nodes)
        miner_scores = calculate_miner_scores(node_scores)
        score_by_hotkey = {score.miner_hotkey: score.total for score in miner_scores}

        hotkey_to_uid = {hotkey: uid for uid, hotkey in enumerate(self.metagraph.hotkeys)}
        reward_uids = []
        reward_values = []
        active_uids = set()
        for hotkey in miner_hotkeys:
            uid = hotkey_to_uid.get(hotkey)
            if uid is None:
                continue
            reward_uids.append(uid)
            reward_values.append(float(score_by_hotkey.get(hotkey, 0.0)))
            if hotkey in verified_hotkeys:
                active_uids.add(int(uid))

        if reward_uids:
            rewards = np.asarray(reward_values, dtype=np.float32)
            uids = np.asarray(reward_uids, dtype=np.int64)

            # EMA smoothing to avoid abrupt weight shifts between verification rounds.
            ema_alpha = float(self.config.validator.ema_alpha)
            previous_scores = self.scores[uids]
            smoothed_rewards, self.ema_initialized_uids = apply_reward_ema(
                rewards=rewards,
                uids=uids,
                previous_scores=previous_scores,
                ema_alpha=ema_alpha,
                ema_initialized_uids=self.ema_initialized_uids,
                active_uids=active_uids,
            )

            self.update_scores(smoothed_rewards, uids)
            bt.logging.info(
                f"Updated rewards for {len(reward_uids)} miners "
                f"(verified={len(active_uids)}, zeroed={len(reward_uids) - len(active_uids)}, ema_alpha={ema_alpha})"
            )

            # Set weights immediately after completing a full scoring cycle.
            if not self.config.neuron.disable_set_weights:
                self.set_weights()
                bt.logging.info("Set weights after full verification cycle")
        else:
            bt.logging.warning("No miner rewards were computed in this verification cycle")

        latencies = [n.avg_latency_ms for n in miner_nodes if n.avg_latency_ms is not None]
        latency_stats = LatencyStats.from_latencies(latencies)
        unique_miners = set(n.miner_hotkey for n in miner_nodes)

        log_verification_metrics(
            self.wandb,
            step=self.step,
            block=self.block,
            verified_count=verified_count,
            failed_count=failed_count,
            total_nodes=len(miner_nodes),
            total_miners=len(unique_miners),
            latency_stats=latency_stats,
        )


if __name__ == "__main__":
    with Validator() as validator:
        while True:
            bt.logging.info(f"Validator running... {time.time()}")
            time.sleep(5)
