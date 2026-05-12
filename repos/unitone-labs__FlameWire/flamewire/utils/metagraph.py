# The MIT License (MIT)
# Copyright © 2026 UnitOne Labs

from typing import List


def get_miner_hotkeys(metagraph, validator_uid: int) -> List[str]:
    """
    Get all miner hotkeys from the metagraph.

    Args:
        metagraph: The bittensor metagraph object
        validator_uid: The UID of the current validator (to exclude)

    Returns:
        List of miner hotkey addresses
    """
    miners = []
    for neuron in metagraph.neurons:
        if neuron.uid != validator_uid and neuron.validator_trust == 0:
            miners.append(neuron.hotkey)
    return miners
