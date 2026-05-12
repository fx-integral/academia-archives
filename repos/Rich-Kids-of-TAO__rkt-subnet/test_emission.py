import bittensor as bt
from rich_kids_of_tao.emission_checker import (
    check_hotkey_emissions,
    process_emissions_and_rewards,
    fetch_subnet_weights_from_api,
)


def main():
    bt.logging.set_debug(True)
    bt.logging.set_trace(True)

    bt.logging.info("=== Miner Appreciation Test Runner ===")

    # Add test hotkeys here to test emission checking
    test_hotkeys = []

    # Test netuid (our subnet)
    TEST_NETUID = 110

    # Fetch subnet weights from API
    SUBNETS_TO_CHECK = fetch_subnet_weights_from_api()

    try:
        subtensor = bt.subtensor(network="finney")
        bt.logging.info("Connected to subtensor")
    except Exception as e:
        bt.logging.error(f"Failed to connect to subtensor: {e}")
        return

    bt.logging.info(f"Fetching prices for subnets: {list(SUBNETS_TO_CHECK.keys())}")
    subnet_prices = {}
    try:
        for netuid in SUBNETS_TO_CHECK.keys():
            try:
                price = subtensor.get_subnet_price(netuid=netuid)
                subnet_prices[netuid] = price.tao
                bt.logging.info(f"Netuid {netuid}: price = {price.tao:.4f}")
            except Exception as e:
                bt.logging.warning(f"Could not get price for netuid {netuid}: {e}")
                subnet_prices[netuid] = 1.0
        bt.logging.info(f"Fetched prices for {len(subnet_prices)} subnets")
    except Exception as e:
        bt.logging.error(f"Failed to fetch subnet prices: {e}")
        subnet_prices = {}

    bt.logging.info(f"Fetching metagraphs for subnets: {list(SUBNETS_TO_CHECK.keys())}")
    subnet_metagraphs = {}
    try:
        for netuid in SUBNETS_TO_CHECK.keys():
            try:
                metagraph = subtensor.metagraph(netuid)
                subnet_metagraphs[netuid] = metagraph
                bt.logging.info(
                    f"Netuid {netuid}: metagraph loaded ({metagraph.n} neurons)"
                )
            except Exception as e:
                bt.logging.warning(f"Could not get metagraph for netuid {netuid}: {e}")
        bt.logging.info(f"Fetched metagraphs for {len(subnet_metagraphs)} subnets")
    except Exception as e:
        bt.logging.error(f"Failed to fetch subnet metagraphs: {e}")
        subnet_metagraphs = {}

    bt.logging.info("=== Testing emission checking with test hotkeys ===")

    all_miner_uids = []
    miner_emissions = {}

    for uid, hotkey in enumerate(test_hotkeys):
        bt.logging.info(f"Testing UID {uid} with hotkey: {hotkey}")
        all_miner_uids.append(uid)

        total_emission_value = check_hotkey_emissions(
            subtensor,
            hotkey,
            TEST_NETUID,
            subnet_prices,
            SUBNETS_TO_CHECK,
            subnet_metagraphs,
        )
        miner_emissions[uid] = total_emission_value

        bt.logging.info(f"UID {uid}: Total emission value={total_emission_value:.6f}")

    if not all_miner_uids:
        bt.logging.info("No test miners found (add hotkeys to test_hotkeys list)")
        return

    emission_values, rewards = process_emissions_and_rewards(
        all_miner_uids, miner_emissions
    )

    bt.logging.info("=== Test Results Summary ===")
    for i, uid in enumerate(all_miner_uids):
        bt.logging.info(
            f"UID {uid}: Emission Value={miner_emissions[uid]:.6f}, Reward={rewards[i]:.6f}"
        )

    bt.logging.info("=== Test Complete ===")


if __name__ == "__main__":
    main()
