"""Tests for the Bittensor miner neuron integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from djinn_miner.bt.neuron import DjinnMiner


class TestDjinnMinerInit:
    def test_defaults(self) -> None:
        m = DjinnMiner()
        assert m.netuid == 103
        assert m.network == "finney"
        assert m._axon_port == 8422
        assert m.wallet is None
        assert m.uid is None

    def test_custom_params(self) -> None:
        m = DjinnMiner(
            netuid=42,
            network="test",
            wallet_name="mywallet",
            hotkey_name="myhotkey",
            axon_port=9999,
            external_ip="1.2.3.4",
        )
        assert m.netuid == 42
        assert m.network == "test"
        assert m._axon_port == 9999
        assert m._external_ip == "1.2.3.4"


class TestSetupWithoutBittensor:
    def test_setup_fails_without_bt(self) -> None:
        m = DjinnMiner()
        with patch("djinn_miner.bt.neuron.bt", None):
            assert m.setup() is False

    def test_setup_catches_exceptions(self) -> None:
        mock_bt = MagicMock()
        mock_bt.wallet.side_effect = RuntimeError("no wallet")
        m = DjinnMiner()
        with patch("djinn_miner.bt.neuron.bt", mock_bt):
            assert m.setup() is False


class TestSetupSuccess:
    def _make_mock_bt(self, hotkey: str = "5FakeHotkey", n: int = 256) -> MagicMock:
        mock_bt = MagicMock()

        # Wallet (code calls bt.Wallet — capital W)
        wallet = MagicMock()
        wallet.hotkey.ss58_address = hotkey
        mock_bt.Wallet.return_value = wallet

        # Subtensor (code calls bt.Subtensor — capital S)
        subtensor = MagicMock()
        mock_bt.Subtensor.return_value = subtensor

        # Metagraph
        metagraph = MagicMock()
        metagraph.n.item.return_value = n
        metagraph.hotkeys = [f"key-{i}" for i in range(n)]
        metagraph.hotkeys[42] = hotkey
        subtensor.metagraph.return_value = metagraph

        # Axon (code calls bt.Axon — capital A)
        axon = MagicMock()
        mock_bt.Axon.return_value = axon

        return mock_bt

    def test_setup_succeeds(self) -> None:
        mock_bt = self._make_mock_bt()
        m = DjinnMiner()
        with patch("djinn_miner.bt.neuron.bt", mock_bt):
            assert m.setup() is True
        assert m.uid == 42
        assert m.wallet is not None
        assert m.subtensor is not None
        assert m.axon is not None

    def test_setup_not_registered(self) -> None:
        mock_bt = self._make_mock_bt(hotkey="unknown-key")
        # hotkey not in metagraph.hotkeys
        mock_bt.Subtensor.return_value.metagraph.return_value.hotkeys = ["other"]
        m = DjinnMiner()
        with patch("djinn_miner.bt.neuron.bt", mock_bt):
            assert m.setup() is False
        assert m.uid is None

    def test_axon_served(self) -> None:
        mock_bt = self._make_mock_bt()
        m = DjinnMiner(axon_port=7777, external_ip="10.0.0.1")
        with patch("djinn_miner.bt.neuron.bt", mock_bt):
            m.setup()
        mock_bt.Axon.assert_called_once()
        m.subtensor.serve_axon.assert_called_once()


class TestSyncMetagraph:
    def test_sync_calls_subtensor(self) -> None:
        m = DjinnMiner()
        m.subtensor = MagicMock()
        m.metagraph = MagicMock()
        m.metagraph.n.item.return_value = 128
        m.sync_metagraph()
        m.metagraph.sync.assert_called_once_with(subtensor=m.subtensor)

    def test_sync_noop_without_subtensor(self) -> None:
        m = DjinnMiner()
        m.sync_metagraph()  # No error


class TestIsRegistered:
    def test_registered(self) -> None:
        m = DjinnMiner()
        m.wallet = MagicMock()
        m.wallet.hotkey.ss58_address = "mykey"
        m.metagraph = MagicMock()
        m.metagraph.hotkeys = ["other", "mykey"]
        assert m.is_registered() is True

    def test_not_registered(self) -> None:
        m = DjinnMiner()
        m.wallet = MagicMock()
        m.wallet.hotkey.ss58_address = "mykey"
        m.metagraph = MagicMock()
        m.metagraph.hotkeys = ["other"]
        assert m.is_registered() is False

    def test_no_metagraph(self) -> None:
        m = DjinnMiner()
        assert m.is_registered() is False


class TestBlock:
    def test_block_returns_subtensor_block(self) -> None:
        m = DjinnMiner()
        m.subtensor = MagicMock()
        m.subtensor.block = 12345
        assert m.block == 12345

    def test_block_zero_without_subtensor(self) -> None:
        m = DjinnMiner()
        assert m.block == 0


class TestSetupWalletNotFound:
    def test_wallet_not_found(self) -> None:
        """FileNotFoundError in setup returns False with specific logging."""
        mock_bt = MagicMock()
        mock_bt.wallet.side_effect = FileNotFoundError("~/.bittensor/wallets/default")
        m = DjinnMiner()
        with patch("djinn_miner.bt.neuron.bt", mock_bt):
            assert m.setup() is False


class TestSetupAxonWithoutWallet:
    def test_axon_setup_skipped_without_wallet(self) -> None:
        """_setup_axon is a no-op if wallet is None."""
        m = DjinnMiner()
        m._setup_axon()  # Should not raise
        assert m.axon is None

    def test_axon_setup_skipped_without_bt(self) -> None:
        """_setup_axon is a no-op if bittensor not installed."""
        m = DjinnMiner()
        m.wallet = MagicMock()
        with patch("djinn_miner.bt.neuron.bt", None):
            m._setup_axon()
        assert m.axon is None
