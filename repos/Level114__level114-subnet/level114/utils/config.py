# The MIT License (MIT)
# Copyright © 2025 Level114 Team

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
import torch
import argparse
import bittensor as bt
from loguru import logger


def check_config(cls, config: "bt.Config"):
    r"""Checks/validates the config namespace object."""
    bt.logging.check_config(config)
    
    # Remove axon checks; validator does not serve axon
    
    # Check subtensor config if it exists
    if hasattr(bt.subtensor, 'check_config'):
        bt.subtensor.check_config(config)
    
    # Check wallet config if it exists  
    if hasattr(bt.wallet, 'check_config'):
        bt.wallet.check_config(config)

    full_path = os.path.expanduser(
        "{}/{}/{}/netuid{}/{}".format(
            config.logging.logging_dir,  # TODO: change from ~/.bittensor/miners to ~/.bittensor/neurons
            config.wallet.name,
            config.wallet.hotkey,
            config.netuid,
            cls.__name__,
        )
    )
    config.neuron.full_path = os.path.expanduser(full_path)
    if not os.path.exists(config.neuron.full_path):
        os.makedirs(config.neuron.full_path, exist_ok=True)

    # Ensure collector namespace exists
    if not hasattr(config, 'collector'):
        config.collector = bt.Config()
    if not hasattr(config.collector, 'url'):
        config.collector.url = "http://localhost:8000"
    if not hasattr(config.collector, 'timeout'):
        config.collector.timeout = 10.0
    if not hasattr(config.collector, 'api_key'):
        config.collector.api_key = None
    if not hasattr(config.collector, 'reports_limit'):
        config.collector.reports_limit = 25


def add_args(cls, parser):
    """
    Adds relevant arguments to the parser for operation.
    """
    # Netuid Arg: The netuid of the subnet to connect to.
    parser.add_argument("--netuid", type=int, help="Subnet netuid", default=1)

    # Collector args are added via add_collector_args(parser)

    neuron_group = parser.add_argument_group('neuron')
    neuron_group.add_argument(
        "--neuron.device",
        type=str,
        help="Device to run on.",
        default="cuda" if torch.cuda.is_available() else "cpu",
    )
    
    neuron_group.add_argument(
        "--neuron.epoch_length",
        type=int,
        help="The default epoch length (how often we sync metagraph, etc).",
        default=100,
    )

    neuron_group.add_argument(
        "--neuron.events_retention_size",
        type=str,
        help="Events retention size.",
        default="2 GB",
    )

    neuron_group.add_argument(
        "--neuron.dont_save_events",
        action="store_true",
        help="If set, we dont save events to a log file.",
        default=False,
    )

    neuron_group.add_argument(
        "--neuron.disable_set_weights",
        action="store_true",
        help="Disables setting weights.",
        default=False,
    )

    neuron_group.add_argument(
        "--neuron.moving_average_alpha",
        type=float,
        help="Moving average alpha parameter, how much to add of the new observation.",
        default=0.05,
    )


    neuron_group.add_argument(
        "--neuron.sample_size",
        type=int,
        help="The number of miners to query each step.",
        default=10,
    )


def add_collector_args(parser: argparse.ArgumentParser):
    collector_group = parser.add_argument_group('collector')
    collector_group.add_argument("--collector.url", type=str, help="Collector base URL", default=None)
    collector_group.add_argument("--collector.timeout", type=float, help="Collector timeout seconds", default=10.0)
    collector_group.add_argument("--collector.api_key", type=str, help="Collector API key (Bearer)", default=None)
    collector_group.add_argument("--collector.reports_limit", type=int, help="Default reports limit", default=25)


def add_validator_args(cls, parser):
    """Add validator specific arguments to the parser."""
    
    validator_group = parser.add_argument_group('validator')
    
    validator_group.add_argument(
        "--validator.query_timeout",
        type=float,
        help="Timeout for querying miners",
        default=12.0,
    )
    
    validator_group.add_argument(
        "--validator.challenge_interval",
        type=int,
        help="How often to challenge miners (steps)",
        default=5,
    )
    
    # Level114 scoring system arguments
    validator_group.add_argument(
        "--validator.weight_update_interval",
        type=int,
        help="Interval in seconds between weight updates (fixed at 1200 = 20 minutes; lower values are ignored)",
        default=1200,
    )

    validator_group.add_argument(
        "--validator.validation_interval",
        type=int,
        help="Interval in seconds between validation cycles (default: 1440 = 24 minutes)",
        default=24 * 60,
    )


def config(cls):
    """
    Returns the configuration object specific to this miner or validator after adding relevant arguments.
    """
    parser = argparse.ArgumentParser()
    bt.wallet.add_args(parser)
    bt.subtensor.add_args(parser)
    bt.logging.add_args(parser)
    add_collector_args(parser)
    cls.add_args(parser)
    return bt.config(parser)
