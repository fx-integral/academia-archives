import bittensor as bt
import requests
from typing import List, Dict, Tuple


def fetch_subnet_weights_from_api(
    api_url: str = "https://richkidsoftao.com/api/subnets",
) -> dict:
    """Fetch subnet weights from centralized API"""
    bt.logging.info(f"Fetching subnet weights from API: {api_url}")
    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        data = response.json()

        subnet_weights = data.get("subnets", {})
        bt.logging.info(f"Fetched subnet weights from API: {subnet_weights}")

        # Convert string keys to int if needed
        subnet_weights = {int(k): v for k, v in subnet_weights.items()}

        return subnet_weights
    except Exception as e:
        bt.logging.error(f"Failed to fetch from API: {e}")
        return {}


def check_hotkey_emissions(
    subtensor,
    hotkey: str,
    our_netuid: int,
    subnet_prices: dict = None,
    subnets_to_check: dict = None,
    subnet_metagraphs: dict = None,
) -> float:
    try:
        total_emission_value = 0.0

        # Use predefined dict (with weights) or check all subnets
        if subnets_to_check:
            netuids_dict = subnets_to_check
        else:
            all_subnets = subtensor.all_subnets()
            netuids_dict = {subnet.netuid: 1.0 for subnet in all_subnets}

        for netuid, subnet_weight in netuids_dict.items():
            # Skip our own subnet
            if netuid == our_netuid:
                continue

            try:
                # Get the metagraph for this subnet (use cached if available)
                if subnet_metagraphs and netuid in subnet_metagraphs:
                    metagraph = subnet_metagraphs[netuid]
                else:
                    metagraph = subtensor.metagraph(netuid)

                # Find our hotkey in this subnet
                if hotkey not in metagraph.hotkeys:
                    bt.logging.info(f"Netuid {netuid}: Hotkey not found")
                    continue

                # Get the hotkey's index
                uid = metagraph.hotkeys.index(hotkey)

                # Get emission for this hotkey
                emission = metagraph.E[uid].item()

                # Get subnet price
                price = subnet_prices.get(netuid, 1.0) if subnet_prices else 1.0

                # Calculate emission value with subnet weight
                emission_value = emission * price * subnet_weight
                total_emission_value += emission_value

                bt.logging.info(
                    f"Netuid {netuid}: {emission:.6f} emission * {price:.4f} price * {subnet_weight:.2f} weight = {emission_value:.6f} value"
                )

            except Exception as e:
                bt.logging.warning(f"Netuid {netuid}: Could not check - {e}")
                continue

        bt.logging.info(
            f"Hotkey {hotkey}: Total emission value = {total_emission_value:.6f}"
        )

        return total_emission_value
    except Exception as e:
        bt.logging.warning(f"Could not get emissions for hotkey {hotkey}: {e}")
        return 0.0


def check_uid_availability(metagraph, uid: int, vpermit_tao_limit: int = 1024) -> bool:
    if metagraph.validator_permit[uid]:
        if metagraph.S[uid] > vpermit_tao_limit:
            bt.logging.debug(
                f"UID {uid}: High-stake validator (stake: {metagraph.S[uid]:.2f})"
            )
            return False
    return True


def check_metagraph_emissions(
    validator_self,
) -> Tuple[List[int], Dict[int, float]]:
    all_miner_uids = []
    miner_emissions = {}
    processed_hotkeys = set()

    for uid in range(validator_self.metagraph.n.item()):
        # Skip UID 0 (burner) unless we want to burn emissions
        if uid == 0 and validator_self.burner_weight == 0.0:
            bt.logging.debug(f"UID {uid}: Skipping burner UID (burn disabled)")
            continue

        uid_is_available = check_uid_availability(validator_self.metagraph, uid)

        if uid_is_available:
            hotkey = validator_self.metagraph.hotkeys[uid]

            if hotkey in processed_hotkeys:
                bt.logging.info(
                    f"UID {uid}: Skipping (hotkey {hotkey} already processed)"
                )
                miner_emissions[uid] = 0.0
                all_miner_uids.append(uid)
                continue

            processed_hotkeys.add(hotkey)
            all_miner_uids.append(uid)

            bt.logging.info(f"Checking UID {uid} with hotkey: {hotkey}")

            total_emission_value = check_hotkey_emissions(
                validator_self.subtensor,
                hotkey,
                validator_self.config.netuid,
                validator_self.subnet_prices,
                validator_self.subnets_to_check,
                validator_self.subnet_metagraphs,
            )
            miner_emissions[uid] = total_emission_value

            bt.logging.info(
                f"UID {uid}: Total emission value={total_emission_value:.6f}"
            )
        else:
            bt.logging.debug(f"UID {uid}: Not available")

    bt.logging.info(
        f"Found {len(all_miner_uids)} available miners out of {validator_self.metagraph.n.item()} total UIDs"
    )
    bt.logging.info(f"Processed {len(processed_hotkeys)} unique hotkeys")
    return all_miner_uids, miner_emissions


def get_rewards_from_emissions(emission_values: List[float]):
    import numpy as np

    emission_array = np.array(emission_values, dtype=np.float32)

    if len(emission_array) == 0:
        return np.array([])

    if np.all(emission_array == 0):
        return np.ones_like(emission_array) / len(emission_array)

    max_emission = np.max(emission_array)
    if max_emission > 0:
        normalized_rewards = emission_array / max_emission
    else:
        normalized_rewards = np.zeros_like(emission_array)

    return normalized_rewards


def process_emissions_and_rewards(
    all_miner_uids: List[int], miner_emissions: Dict[int, float]
) -> Tuple[List[float], List[float]]:
    if not all_miner_uids:
        return [], []

    emission_values = [miner_emissions.get(uid, 0.0) for uid in all_miner_uids]
    rewards = get_rewards_from_emissions(emission_values)

    bt.logging.info(f"Emission values: {[f'{w:.6f}' for w in emission_values]}")
    bt.logging.info(f"Calculated rewards: {[f'{r:.6f}' for r in rewards]}")

    for uid, reward in zip(all_miner_uids, rewards):
        bt.logging.info(f"UID {uid}: Reward={reward:.6f}")

    return emission_values, rewards
