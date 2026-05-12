import copy
import bittensor
import argparse
from bittensor.core.config import Config, DefaultMunch


def test_py_config_parsed_successfully_rust_wallet():
    """Verify that python based config object is successfully parsed with rust-based wallet object."""
    parser = argparse.ArgumentParser()

    bittensor.Wallet.add_args(parser)
    bittensor.Subtensor.add_args(parser)
    bittensor.Axon.add_args(parser)
    bittensor.logging.add_args(parser)

    config = bittensor.Config(parser)

    # override config manually since we can't apply mocking to rust objects easily
    config.wallet.name = "new_wallet_name"
    config.wallet.hotkey = "new_hotkey"
    config.wallet.path = "/some/not_default/path"

    # Pass in the whole bittensor config
    wallet = bittensor.Wallet(config=config)
    assert wallet.name == config.wallet.name
    assert wallet.hotkey_str == config.wallet.hotkey
    assert wallet.path == config.wallet.path

    # Pass in only the btwallet's config
    wallet_two = bittensor.Wallet(config=config.wallet)
    assert wallet_two.name == config.wallet.name
    assert wallet_two.hotkey_str == config.wallet.hotkey
    assert wallet_two.path == config.wallet.path


def test_deepcopy_default_munch():
    """
    deepcopy of a nested DefaultMunch must not fail via __reduce_ex__.

    In Python 3.10, copy.deepcopy falls back to getattr(x, "__reduce_ex__") for
    dict subclasses that are not in _deepcopy_dispatch.  DefaultMunch.__getattr__
    intercepts that lookup and returns None (the configured default value) instead
    of the real method, causing TypeError: 'NoneType' object is not callable.
    DefaultMunch.__deepcopy__ prevents this by giving deepcopy an explicit path.
    """
    original = DefaultMunch.fromDict(
        {"port": 8091, "ip": "[::]", "external_port": None, "nested": {"x": 1}}
    )
    cloned = copy.deepcopy(original)

    assert cloned.port == 8091
    assert cloned.ip == "[::]"
    assert cloned.external_port is None
    assert cloned.nested.x == 1

    # Mutations to the clone must not affect the original
    cloned.port = 9999
    cloned.nested.x = 42
    assert original.port == 8091
    assert original.nested.x == 1


def test_deepcopy_config_with_nested_defaults():
    """deepcopy of a full Config (including nested DefaultMunch values) works."""
    parser = argparse.ArgumentParser()
    bittensor.Subtensor.add_args(parser)
    config = Config(parser)

    cloned = copy.deepcopy(config)

    assert cloned.subtensor.network == config.subtensor.network

    # Mutations to the clone must not affect the original
    cloned.subtensor.network = "mutated"
    assert config.subtensor.network != "mutated"
