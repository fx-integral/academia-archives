"""Tests for peer notary requirement on miners."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from djinn_miner.core.tlsn import (
    TLSNProofResult,
    generate_proof,
)


def _mock_open_connection() -> AsyncMock:
    """Mock asyncio.open_connection so the notary reachability probe in
    generate_proof() succeeds without actually opening a TCP socket."""
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return AsyncMock(return_value=(MagicMock(), writer))


class TestPeerNotaryRequired:
    """Test that miners require a peer notary (no centralized fallback)."""

    @pytest.mark.asyncio
    async def test_no_notary_fails(self) -> None:
        """Miner rejects attestation when no notary is assigned."""
        # No notary host AND no local sidecar reachable → must fail.
        with (
            patch("djinn_miner.core.tlsn.NOTARY_HOST", ""),
            patch(
                "djinn_miner.core.tlsn.asyncio.open_connection",
                side_effect=ConnectionRefusedError("no local sidecar"),
            ),
        ):
            result = await generate_proof("https://example.com")

        assert result.success is False
        assert "notary" in result.error.lower()

    @pytest.mark.asyncio
    async def test_peer_notary_works(self) -> None:
        """When notary_host is provided, attestation proceeds."""

        async def mock_ws_prover(*args, **kwargs):
            return TLSNProofResult(success=True, server="example.com")

        with (
            patch(
                "djinn_miner.core.tlsn.asyncio.open_connection",
                _mock_open_connection(),
            ),
            patch("djinn_miner.core.tlsn._run_prover_via_ws", side_effect=mock_ws_prover),
        ):
            result = await generate_proof(
                "https://example.com",
                notary_host="10.0.0.5",
                notary_port=8422,
                notary_ws=True,
            )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_custom_notary_host_env(self) -> None:
        """When TLSN_NOTARY_HOST is set, it's used as the default notary."""

        async def mock_prover(*args, **kwargs):
            return TLSNProofResult(success=True, server="example.com")

        with (
            patch("djinn_miner.core.tlsn.NOTARY_HOST", "custom-notary.example.com"),
            patch(
                "djinn_miner.core.tlsn.asyncio.open_connection",
                _mock_open_connection(),
            ),
            patch("djinn_miner.core.tlsn._run_prover", side_effect=mock_prover),
        ):
            result = await generate_proof("https://example.com")

        assert result.success is True
