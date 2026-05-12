#!/usr/bin/env python3

import argparse
import bittensor as bt
from rich_kids_of_tao.validator import RichKidsValidator


def main():
    parser = argparse.ArgumentParser()
    RichKidsValidator.add_args(parser)
    config = bt.config(parser)

    validator = RichKidsValidator(config)
    validator.run()


if __name__ == "__main__":
    main()
