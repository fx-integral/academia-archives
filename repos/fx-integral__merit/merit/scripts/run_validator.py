import bittensor as bt
import argparse
import asyncio
from merit.neuron.validator import Validator

def main():
    parser = argparse.ArgumentParser()
    bt.wallet.add_args(parser)
    bt.subtensor.add_args(parser)
    bt.axon.add_args(parser)  # Future-proofing (currently validator doesn't bind axon)
    bt.logging.add_args(parser)

    parser.add_argument("--netuid",
                        type=int,
                        required=True,
                        help="Subnet netuid to validate.")

    parser.add_argument("--ping_frequency",
                        type=int,
                        default=None,
                        help="Optional ping frequency in seconds.")

    parser.add_argument("--no_zero_weights",
                        action="store_true",
                        help="Evenly split weights across miners if all scores are zero instead of skipping.")

    config = bt.config(parser=parser)
    bt.logging(config=config)

    validator = Validator(config=config)
    asyncio.run(validator.run())

if __name__ == "__main__":
    main()
