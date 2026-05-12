# The MIT License (MIT)
# Copyright © 2023 Yuma
# Copyright © 2023 Natix

import time
import warnings

import bittensor as bt

from natix.miner.neuron import Miner


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    with Miner() as miner:
        while True:
            bt.logging.info(
                "Miner | "
                f"UID:{miner.uid} | "
                f"Stake:{miner.metagraph.S[miner.uid]:.3f} | "
                f"Trust:{miner.metagraph.T[miner.uid]:.3f} | "
                f"Incentive:{miner.metagraph.I[miner.uid]:.3f} | "
                f"Emission:{miner.metagraph.E[miner.uid]:.3f}"
            )
            time.sleep(5)
