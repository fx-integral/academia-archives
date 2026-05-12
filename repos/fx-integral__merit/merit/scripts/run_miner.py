import bittensor as bt
import argparse
from merit.neuron.miner import Miner

def main():
    parser = argparse.ArgumentParser()
    bt.wallet.add_args(parser)
    bt.subtensor.add_args(parser)
    bt.axon.add_args(parser)
    bt.logging.add_args(parser)

    parser.add_argument("--netuid", type=int, required=True, help="Subnet netuid to mine on.")

    config = bt.config(parser=parser)
    bt.logging(config=config)

    miner = Miner(config=config)
    miner.run()

if __name__ == "__main__":
    main()
