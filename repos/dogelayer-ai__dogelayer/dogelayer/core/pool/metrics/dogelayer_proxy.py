"""
Proxy pool metrics implementation for time-based queries.
"""

from dataclasses import dataclass

from dogelayer.core.pool.proxy.pool import ProxyPool
from .base import BaseMetrics


@dataclass
class ProxyMetrics(BaseMetrics):
    """
    Mining Metrics for Proxy pool.
    Contains data about the miner's hashrate and shares for a specific time range.
    """

    hashrate: float = 0.0
    shares: int = 0
    share_value: float = 0.0

    def get_share_value_fiat(self, coin_price: float, coin_difficulty: float) -> float:
        """
        Returns the share value for this time period.
        The share value is already calculated by the pool based on actual work done.

        Args:
            coin_price: Current coin price in USD (LTC/DOGE)
            coin_difficulty: Current network difficulty for the coin

        Returns:
            float: Share value in USD
        """
        import os
        import logging
        
        # Development mode settings
        DEV_REWARD_FACTOR = float(os.getenv('DEV_REWARD_FACTOR', '1.0'))

        logging.info(f"get_share_value_fiat DEBUG - Input params: coin_price={coin_price}, coin_difficulty={coin_difficulty}")
        logging.info(f"get_share_value_fiat DEBUG - Miner data: hashrate={self.hashrate}, shares={self.shares}, raw_share_value={self.share_value}")
        
        if self.share_value:
            # For merged mining (LTC+DOGE), use appropriate block reward multiplier
            # LTC block reward is 6.25, DOGE varies but average ~10000
            # Using a combined factor for merged mining rewards
            base_value = (self.share_value / coin_difficulty) * 6.25 * coin_price
            
            # Apply development mode
            calculated_value = base_value * DEV_REWARD_FACTOR

            logging.info(f"get_share_value_fiat DEBUG - Base value: {base_value:.8f}")
            if DEV_REWARD_FACTOR != 1.0:
                logging.info(f"get_share_value_fiat DEBUG - Applied DEV_REWARD_FACTOR: {DEV_REWARD_FACTOR}x")
                logging.info(f"get_share_value_fiat DEBUG - Final calculated value: {calculated_value:.8f}")
                
            return calculated_value
        else:
            logging.warning(f"get_share_value_fiat DEBUG - share_value is 0 or None: {self.share_value}")
            return 0.0


def get_metrics_timerange(
    pool: ProxyPool,
    hotkeys: list[str],
    block_at_registration: list[int],
    start_time: int,
    end_time: int,
    coin: str = "litecoin",
) -> list[ProxyMetrics]:
    """
    Retrieves mining metrics for all miners for a specific time range.

    Args:
        pool: The pool instance to query (must be ProxyPool)
        hotkeys: List of miner hotkeys
        block_at_registration: List of registration blocks for each hotkey
        start_time: Start time as unix timestamp
        end_time: End time as unix timestamp
        coin: The coin type (default: "bitcoin")

    Returns:
        List of ProxyMetrics for each hotkey
    """
    metrics = []
    all_workers = pool.get_miner_contributions_timerange(start_time, end_time, coin)

    import logging
    logging.info(f"Retrieved {len(all_workers)} workers from pool API")
    if all_workers:
        # Show sample worker IDs to help debug format
        sample_keys = list(all_workers.keys())[:3]
        logging.info(f"Sample worker IDs: {sample_keys}")

    hotkeys_to_workers = {}
    worker_ids_to_hotkey_idx = {}

    # Build mapping: support two formats
    # Format 1: Full hotkey (e.g., 5GrwvaEF...utQY)
    # Format 2: Full hotkey with suffix (e.g., 5GrwvaEF...utQY.rig001)
    for i, hotkey in enumerate(hotkeys):
        worker_ids = []

        # Priority 1: Try exact match (full hotkey without suffix)
        if hotkey in all_workers:
            worker_ids.append(hotkey)
            logging.debug(f"Found worker using full hotkey: {hotkey}")

        # Priority 2: Try suffix matching (hotkey.xxx format)
        # Search for all workers that start with this hotkey followed by a dot
        for worker_id in all_workers.keys():
            if "." in worker_id:
                # Extract the hotkey part (before the first dot)
                worker_hotkey = worker_id.split(".")[0]
                if worker_hotkey == hotkey:
                    worker_ids.append(worker_id)
                    logging.info(f"✅ Found worker with suffix: {worker_id} matches hotkey: {hotkey[:8]}...{hotkey[-8:]}")

        # If we found multiple workers with the same hotkey (e.g., hotkey.rig001, hotkey.rig002)
        # we need to aggregate their data
        if len(worker_ids) > 1:
            logging.info(f"📊 Found {len(worker_ids)} workers for hotkey {hotkey[:8]}...{hotkey[-8:]}, will aggregate their data")
            # Store all worker IDs for this hotkey
            hotkeys_to_workers[hotkey] = worker_ids
        elif len(worker_ids) == 1:
            worker_id = worker_ids[0]
            if worker_id in worker_ids_to_hotkey_idx:
                # Duplicate worker ID - choose the older registration
                other_hotkey_idx = worker_ids_to_hotkey_idx[worker_id]
                if block_at_registration[i] < block_at_registration[other_hotkey_idx]:
                    # Current hotkey registered earlier, use it
                    other_hotkey = hotkeys[other_hotkey_idx]
                    if other_hotkey in hotkeys_to_workers:
                        del hotkeys_to_workers[other_hotkey]
                    worker_ids_to_hotkey_idx[worker_id] = i
                    hotkeys_to_workers[hotkey] = [worker_id]
            else:
                # First time seeing this worker ID
                worker_ids_to_hotkey_idx[worker_id] = i
                hotkeys_to_workers[hotkey] = [worker_id]

    for hotkey in hotkeys:
        worker_ids = hotkeys_to_workers.get(hotkey)

        if worker_ids is None:
            metrics.append(ProxyMetrics(hotkey=hotkey))
            continue

        # Aggregate data from all workers with this hotkey
        total_share_value = 0.0
        total_hashrate = 0.0
        total_shares = 0
        hash_rate_unit = "Gh/s"

        for worker_id in worker_ids:
            worker_data = all_workers.get(worker_id, {})

            # Log worker data for debugging
            if worker_data:
                logging.info(f"✅ Found worker data - hotkey: {hotkey[:8]}...{hotkey[-8:]}, worker_id: {worker_id if len(worker_id) <= 16 else worker_id[:8]+'...'+worker_id[-8:]}")
                logging.debug(f"Worker data: hashrate={worker_data.get('hashrate', 0)}, shares={worker_data.get('shares', 0)}, share_value={worker_data.get('share_value', 0)}")

                # Accumulate values
                total_share_value += worker_data.get("share_value", 0.0)
                total_hashrate += worker_data.get("hashrate", 0.0)
                total_shares += worker_data.get("shares", 0)
                hash_rate_unit = worker_data.get("hash_rate_unit", "Gh/s")
            else:
                logging.warning(f"❌ No worker data found - hotkey: {hotkey[:8]}...{hotkey[-8:]}, worker_id: {worker_id}")
        
        # Log aggregated values
        if len(worker_ids) > 1:
            logging.info(f"📊 Aggregated {len(worker_ids)} workers for hotkey {hotkey[:8]}...{hotkey[-8:]}: "
                        f"total_share_value={total_share_value}, total_hashrate={total_hashrate}, total_shares={total_shares}")
        else:
            logging.info(f"ProxyMetricsCreate - extracted field values: hashrate={total_hashrate}, shares={total_shares}, share_value={total_share_value}")

        metrics.append(
            ProxyMetrics(
                hotkey=hotkey,
                hashrate=total_hashrate,
                shares=total_shares,
                share_value=total_share_value,
                hash_rate_unit=hash_rate_unit,
            )
        )

    return metrics
