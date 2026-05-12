"""Tests for the ChainClient on-chain interaction layer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from djinn_validator.chain.contracts import ChainClient


@pytest.fixture
def client() -> ChainClient:
    """Create a ChainClient with all addresses configured."""
    with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
        mock_w3 = MagicMock()
        mock_w3.to_checksum_address = lambda x: x
        mock_w3.eth = MagicMock()
        mock_contract = MagicMock()
        mock_w3.eth.contract.return_value = mock_contract
        MockW3.return_value = mock_w3
        MockW3.AsyncHTTPProvider = MagicMock()

        c = ChainClient(
            rpc_url="http://localhost:8545",
            escrow_address="0x1111111111111111111111111111111111111111",
            signal_address="0x2222222222222222222222222222222222222222",
            account_address="0x3333333333333333333333333333333333333333",
        )
        c._w3 = mock_w3
        return c


class TestChainClientInit:
    def test_no_contracts_when_addresses_empty(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://localhost:8545")
            assert c._escrow is None
            assert c._signal is None
            assert c._account is None


class TestIsSignalActive:
    @pytest.mark.asyncio
    async def test_returns_true_when_no_contract(self) -> None:
        """Permissive in dev mode: returns True when contract not configured."""
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://localhost:8545")
            assert await c.is_signal_active(1) is True

    @pytest.mark.asyncio
    async def test_calls_contract(self, client: ChainClient) -> None:
        mock_call = AsyncMock(return_value=True)
        client._signal.functions.isActive.return_value.call = mock_call
        result = await client.is_signal_active(42)
        assert result is True
        client._signal.functions.isActive.assert_called_with(42)

    @pytest.mark.asyncio
    async def test_returns_false_for_inactive(self, client: ChainClient) -> None:
        mock_call = AsyncMock(return_value=False)
        client._signal.functions.isActive.return_value.call = mock_call
        result = await client.is_signal_active(99)
        assert result is False


class TestGetSignal:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_contract(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://localhost:8545")
            result = await c.get_signal(1)
            assert result == {}

    @pytest.mark.asyncio
    async def test_parses_contract_result(self, client: ChainClient) -> None:
        # 16-field Signal struct (v2): genius, encryptedBlob, commitHash, sport,
        # maxPriceBps, slaMultiplierBps, maxNotional, minNotional, expiresAt,
        # decoyLines, availableSportsbooks, status, createdAt,
        # linesHash, lineCount, bpaMode
        mock_result = [
            "0xGenius",  # [0] genius
            b"\xab\xcd",  # [1] encryptedBlob
            b"\x00" * 32,  # [2] commitHash
            "basketball_nba",  # [3] sport
            500,  # [4] maxPriceBps
            200,  # [5] slaMultiplierBps
            100_000_000,  # [6] maxNotional
            10_000_000,  # [7] minNotional
            1700100000,  # [8] expiresAt
            ["line1", "line2"],  # [9] decoyLines
            ["draftkings"],  # [10] availableSportsbooks
            1,  # [11] status
            1700000000,  # [12] createdAt
            b"\x00" * 32,  # [13] linesHash
            5,  # [14] lineCount
            False,  # [15] bpaMode
        ]
        mock_call = AsyncMock(return_value=mock_result)
        client._signal.functions.getSignal.return_value.call = mock_call

        result = await client.get_signal(42)
        assert result["genius"] == "0xGenius"
        assert result["sport"] == "basketball_nba"
        assert result["maxPriceBps"] == 500
        assert result["slaMultiplierBps"] == 200
        assert result["expiresAt"] == 1700100000
        assert result["status"] == 1
        assert result["createdAt"] == 1700000000


class TestIsPaused:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_contract(self) -> None:
        """Dev mode with no contract addresses must fail-open (False)."""
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://localhost:8545")
            assert await c.is_paused("escrow") is False
            assert await c.is_paused("signal") is False
            assert await c.is_paused("account") is False

    @pytest.mark.asyncio
    async def test_unknown_subsystem_returns_false(self, client: ChainClient) -> None:
        """Unknown subsystem names fail-open rather than raising — the caller
        treats False as 'proceed as normal', which is the safe default."""
        assert await client.is_paused("bogus") is False
        assert await client.is_paused("") is False

    @pytest.mark.asyncio
    async def test_returns_true_when_contract_paused(self, client: ChainClient) -> None:
        client._escrow.functions.paused.return_value.call = AsyncMock(return_value=True)
        assert await client.is_paused("escrow") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_contract_not_paused(self, client: ChainClient) -> None:
        client._signal.functions.paused.return_value.call = AsyncMock(return_value=False)
        assert await client.is_paused("signal") is False

    @pytest.mark.asyncio
    async def test_read_failure_returns_false(self, client: ChainClient) -> None:
        """Any RPC/ABI failure reading paused() must return False, not raise.
        A false positive would DoS the validator; false negative is status quo."""
        client._account.functions.paused.return_value.call = AsyncMock(side_effect=RuntimeError("rpc down"))
        assert await client.is_paused("account") is False


class TestVerifyPurchase:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_contract(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://localhost:8545")
            result = await c.verify_purchase(1, "0xBuyer")
            assert result["notional"] == 0
            assert result["pricePaid"] == 0

    @pytest.mark.asyncio
    async def test_returns_purchase_data(self, client: ChainClient) -> None:
        # getPurchasesBySignal returns list of purchase IDs
        client._escrow.functions.getPurchasesBySignal.return_value.call = AsyncMock(return_value=[42])
        # getPurchase returns tuple: (idiot, signalId, notional, feePaid, creditUsed, usdcPaid, odds, outcome, purchasedAt, lockedOdds)
        client._escrow.functions.getPurchase.return_value.call = AsyncMock(
            return_value=["0xBuyer", 1, 1000000, 10000, 20000, 30000, 150, 0, 1700000000, 0]
        )

        result = await client.verify_purchase(1, "0xBuyer")
        assert result["notional"] == 1000000
        assert result["pricePaid"] == 50000  # creditUsed + usdcPaid

    @pytest.mark.asyncio
    async def test_returns_zero_when_buyer_not_found(self, client: ChainClient) -> None:
        client._escrow.functions.getPurchasesBySignal.return_value.call = AsyncMock(return_value=[42])
        client._escrow.functions.getPurchase.return_value.call = AsyncMock(
            return_value=["0xOtherBuyer", 1, 1000000, 10000, 20000, 30000, 150, 0, 1700000000, 0]
        )

        result = await client.verify_purchase(1, "0xBuyer")
        assert result["notional"] == 0
        assert result["pricePaid"] == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_purchases(self, client: ChainClient) -> None:
        client._escrow.functions.getPurchasesBySignal.return_value.call = AsyncMock(return_value=[])

        result = await client.verify_purchase(1, "0xBuyer")
        assert result["notional"] == 0
        assert result["pricePaid"] == 0


class TestIsAuditReady:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_contract(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://localhost:8545")
            result = await c.is_audit_ready("0xGenius", "0xIdiot")
            assert result is False

    @pytest.mark.asyncio
    async def test_calls_contract(self, client: ChainClient) -> None:
        mock_call = AsyncMock(return_value=True)
        client._account.functions.isAuditReady.return_value.call = mock_call
        result = await client.is_audit_ready("0xGenius", "0xIdiot")
        assert result is True


class TestIsConnected:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, client: ChainClient) -> None:
        client._w3.eth.block_number = AsyncMock(return_value=12345)
        # The property access needs to be awaited — mock it as a coroutine
        type(client._w3.eth).block_number = property(lambda self: _async_value(12345))
        result = await client.is_connected()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self, client: ChainClient) -> None:
        async def _raise() -> int:
            raise ConnectionError("connection refused")

        type(client._w3.eth).block_number = property(lambda self: _raise())
        result = await client.is_connected()
        assert result is False


class TestVerifyChainId:
    """MAINNET_BLOCKERS P1-23: startup chain_id assertion."""

    @pytest.mark.asyncio
    async def test_passes_when_rpc_chain_id_matches(self, client: ChainClient) -> None:
        client._chain_id = 84532
        type(client._w3.eth).chain_id = property(lambda self: _async_value(84532))
        # No exception => pass.
        await client.verify_chain_id()

    @pytest.mark.asyncio
    async def test_raises_when_rpc_chain_id_diverges(self, client: ChainClient) -> None:
        client._chain_id = 8453  # configured for mainnet
        type(client._w3.eth).chain_id = property(lambda self: _async_value(84532))  # RPC is sepolia
        with pytest.raises(RuntimeError, match="chain_id mismatch"):
            await client.verify_chain_id()

    @pytest.mark.asyncio
    async def test_error_message_includes_both_values(self, client: ChainClient) -> None:
        client._chain_id = 1  # configured for ethereum mainnet
        type(client._w3.eth).chain_id = property(lambda self: _async_value(137))  # RPC is polygon
        with pytest.raises(RuntimeError) as exc_info:
            await client.verify_chain_id()
        assert "BASE_CHAIN_ID=1" in str(exc_info.value)
        assert "chain_id=137" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_propagates_rpc_unreachable(self, client: ChainClient) -> None:
        client._chain_id = 84532

        async def _raise() -> int:
            raise ConnectionError("connection refused")

        type(client._w3.eth).chain_id = property(lambda self: _raise())
        with pytest.raises(ConnectionError):
            await client.verify_chain_id()


class TestWaitForReceipt:
    """MAINNET_BLOCKERS P0-09: receipt-driven settlement."""

    @pytest.mark.asyncio
    async def test_returns_receipt_when_mined(self, client: ChainClient) -> None:
        # First poll returns None, second returns a receipt.
        receipts = [None, {"status": 1, "blockNumber": 123, "transactionHash": "0xabc"}]
        call_count = {"n": 0}

        async def _get_receipt(tx_hash: str) -> dict | None:
            call_count["n"] += 1
            return receipts[min(call_count["n"] - 1, len(receipts) - 1)]

        client._w3.eth.get_transaction_receipt = _get_receipt
        receipt = await client.wait_for_receipt("0xabc", timeout_s=5.0, poll_interval_s=0.01)
        assert receipt["status"] == 1
        assert receipt["blockNumber"] == 123

    @pytest.mark.asyncio
    async def test_returns_reverted_receipt_without_raising(self, client: ChainClient) -> None:
        """Status=0 (revert) must be returned so caller can distinguish drop vs. revert."""

        async def _get_receipt(tx_hash: str) -> dict:
            return {"status": 0, "blockNumber": 456, "transactionHash": "0xdef"}

        client._w3.eth.get_transaction_receipt = _get_receipt
        receipt = await client.wait_for_receipt("0xdef", timeout_s=5.0, poll_interval_s=0.01)
        assert receipt["status"] == 0

    @pytest.mark.asyncio
    async def test_raises_timeout_when_never_mined(self, client: ChainClient) -> None:
        async def _never(tx_hash: str) -> None:
            return None

        client._w3.eth.get_transaction_receipt = _never
        with pytest.raises(TimeoutError, match="not mined within"):
            await client.wait_for_receipt("0x0", timeout_s=0.05, poll_interval_s=0.01)

    @pytest.mark.asyncio
    async def test_retries_through_transient_rpc_errors(self, client: ChainClient) -> None:
        """Hard RPC errors during polling shouldn't abort the wait — just log and retry."""
        call_count = {"n": 0}

        async def _flaky(tx_hash: str) -> dict | None:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("temporary RPC error")
            return {"status": 1, "blockNumber": 789}

        client._w3.eth.get_transaction_receipt = _flaky
        receipt = await client.wait_for_receipt("0xaaa", timeout_s=5.0, poll_interval_s=0.01)
        assert receipt["status"] == 1
        assert call_count["n"] >= 3


class TestClose:
    @pytest.mark.asyncio
    async def test_close_with_session(self, client: ChainClient) -> None:
        mock_session = AsyncMock()
        client._w3.provider._request_session = mock_session
        await client.close()
        # close() now prefers aclose() if available
        mock_session.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_session(self, client: ChainClient) -> None:
        """close() should not raise even if provider has no session."""
        client._w3.provider = MagicMock(spec=[])  # No _request_session attr
        await client.close()  # Should not raise


class TestContractCallErrors:
    """Verify contract methods handle RPC errors gracefully."""

    @pytest.mark.asyncio
    async def test_is_signal_active_rpc_error(self, client: ChainClient) -> None:
        """RPC failure returns False (fail-safe: don't release shares)."""
        mock_call = AsyncMock(side_effect=ConnectionError("RPC down"))
        client._signal.functions.isActive.return_value.call = mock_call
        result = await client.is_signal_active(1)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_signal_rpc_error(self, client: ChainClient) -> None:
        """RPC failure returns empty dict."""
        mock_call = AsyncMock(side_effect=ConnectionError("RPC down"))
        client._signal.functions.getSignal.return_value.call = mock_call
        result = await client.get_signal(1)
        assert result == {}

    @pytest.mark.asyncio
    async def test_verify_purchase_rpc_error(self, client: ChainClient) -> None:
        """RPC failure returns zero values."""
        mock_call = AsyncMock(side_effect=ConnectionError("RPC down"))
        client._escrow.functions.getPurchasesBySignal.return_value.call = mock_call
        result = await client.verify_purchase(1, "0xBuyer")
        assert result["notional"] == 0
        assert result["pricePaid"] == 0
        assert result["sportsbook"] == ""

    @pytest.mark.asyncio
    async def test_is_audit_ready_rpc_error(self, client: ChainClient) -> None:
        """RPC failure returns False."""
        mock_call = AsyncMock(side_effect=ConnectionError("RPC down"))
        client._account.functions.isAuditReady.return_value.call = mock_call
        result = await client.is_audit_ready("0xGenius", "0xIdiot")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_timeout(self, client: ChainClient) -> None:
        """close() handles timeout gracefully."""
        import asyncio

        async def slow_close():
            await asyncio.sleep(10)

        mock_session = MagicMock()
        mock_session.aclose = slow_close
        client._w3.provider._request_session = mock_session
        # Should complete within timeout, not hang forever
        await asyncio.wait_for(client.close(), timeout=10.0)

    @pytest.mark.asyncio
    async def test_close_idempotent(self, client: ChainClient) -> None:
        """Calling close twice should not raise."""
        client._w3.provider = MagicMock(spec=[])
        await client.close()
        await client.close()


class TestRpcFailover:
    """Verify automatic RPC failover when endpoints become unreachable."""

    def test_single_url_init(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://localhost:8545")
            assert c.rpc_url_count == 1
            assert c.rpc_url == "http://localhost:8545"

    def test_comma_separated_urls(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://rpc1:8545 , http://rpc2:8545")
            assert c.rpc_url_count == 2
            assert c.rpc_url == "http://rpc1:8545"

    def test_list_urls(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url=["http://rpc1:8545", "http://rpc2:8545"])
            assert c.rpc_url_count == 2

    def test_rotate_with_single_url_returns_false(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="http://rpc1:8545")
            assert c._rotate_rpc() is False

    def test_rotate_switches_url(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url=["http://rpc1:8545", "http://rpc2:8545"])
            assert c.rpc_url == "http://rpc1:8545"
            assert c._rotate_rpc() is True
            assert c.rpc_url == "http://rpc2:8545"

    @pytest.mark.asyncio
    async def test_failover_on_connection_error(self) -> None:
        """Contract call should failover to next RPC on ConnectionError."""
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            mock_w3.to_checksum_address = lambda x: x
            mock_contract = MagicMock()
            mock_w3.eth.contract.return_value = mock_contract
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()

            c = ChainClient(
                rpc_url=["http://rpc1:8545", "http://rpc2:8545"],
                signal_address="0x2222222222222222222222222222222222222222",
            )

            call_count = 0

            async def _failing_then_ok():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("rpc1 down")
                return True

            c._signal.functions.isActive.return_value.call = _failing_then_ok
            result = await c.is_signal_active(1)
            assert result is True
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_is_connected_tries_all_endpoints(self) -> None:
        """is_connected should try all endpoints before returning False."""
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()

            c = ChainClient(rpc_url=["http://rpc1:8545", "http://rpc2:8545"])

            async def _raise():
                raise ConnectionError("down")

            type(c._w3.eth).block_number = property(lambda self: _raise())
            result = await c.is_connected()
            assert result is False

    def test_empty_url_fallback(self) -> None:
        with patch("djinn_validator.chain.contracts.AsyncWeb3") as MockW3:
            mock_w3 = MagicMock()
            MockW3.return_value = mock_w3
            MockW3.AsyncHTTPProvider = MagicMock()
            c = ChainClient(rpc_url="")
            assert c.rpc_url_count == 1
            assert "base.org" in c.rpc_url


async def _async_value(val: int) -> int:
    return val


class TestEventScanChunkSize:
    """Pin the eth_getLogs chunk size at <= 2000 by default.

    Base Sepolia and Base mainnet public RPCs reject queries with a
    block range above 2000 (-32602 / "query exceeds max block range
    2000"). Pre-v1764 the scan helpers defaulted to 9_999, so every
    chunk failed silently (errors swallowed in the _fetch wrapper)
    and audit_bootstrap could never enumerate SignalCommitted /
    SignalPurchased / AuditSettled events. The on-chain effect was
    48-of-49 OutcomeVoting submissions reverting with
    PurchaseIdsNotSorted because the batch was built from zero-pid
    signals (v1732's chain-derived purchase_id backfill never fired).
    """

    def test_default_chunk_size_fits_under_public_rpc_limit(self) -> None:
        from djinn_validator.chain.contracts import _DEFAULT_EVENT_SCAN_CHUNK_SIZE

        # Public Base RPC caps at 2000; require strict <= so block range
        # `end - start + 1` (which equals chunk_size) stays at-or-under
        # the limit.
        assert _DEFAULT_EVENT_SCAN_CHUNK_SIZE <= 2000, (
            f"chunk size {_DEFAULT_EVENT_SCAN_CHUNK_SIZE} > 2000 — "
            "Base public RPC rejects ranges above 2000 blocks; the scan "
            "helpers will silently return [] and audit_bootstrap will "
            "never find purchase events."
        )
        assert _DEFAULT_EVENT_SCAN_CHUNK_SIZE >= 1, "chunk size must be positive"

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Operators on permissive RPCs (Alchemy, QuickNode, dedicated
        # nodes) can widen the chunk via env var. Verify the override
        # path is wired up.
        monkeypatch.setenv("DJINN_EVENT_SCAN_CHUNK_SIZE", "4500")
        import importlib

        from djinn_validator.chain import contracts as contracts_module

        importlib.reload(contracts_module)
        try:
            assert contracts_module._DEFAULT_EVENT_SCAN_CHUNK_SIZE == 4500
        finally:
            # Restore for other tests in the same process.
            monkeypatch.delenv("DJINN_EVENT_SCAN_CHUNK_SIZE", raising=False)
            importlib.reload(contracts_module)

    def test_all_three_scan_helpers_use_safe_default(self) -> None:
        """get_recent_signal_events, get_recent_signal_purchases, and
        get_recent_audit_settlements must all default to the safe size.

        A drift in any one of them (e.g. someone copy-pasting an older
        9_999 default into a new helper) reproduces the silent-fail bug
        for that event class. Inspect the function signatures.
        """
        import inspect

        from djinn_validator.chain.contracts import (
            ChainClient,
            _DEFAULT_EVENT_SCAN_CHUNK_SIZE,
        )

        for helper in (
            ChainClient.get_recent_signal_events,
            ChainClient.get_recent_signal_purchases,
            ChainClient.get_recent_audit_settlements,
        ):
            sig = inspect.signature(helper)
            chunk_default = sig.parameters["chunk_size"].default
            assert chunk_default == _DEFAULT_EVENT_SCAN_CHUNK_SIZE, (
                f"{helper.__qualname__} chunk_size default {chunk_default} "
                f"!= {_DEFAULT_EVENT_SCAN_CHUNK_SIZE}; chunk-size drift "
                "between helpers will silently break audit_bootstrap"
            )
