"""Tests for TLSNotary proof verification wrapper."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from djinn_validator.core.tlsn import (
    TLSNVerifyResult,
    _HEX_KEY_RE,
    is_available,
    verify_proof,
)


class TestIsAvailable:
    """Test verifier binary availability detection."""

    @patch("djinn_validator.core.tlsn.shutil.which")
    def test_available(self, mock_which: MagicMock) -> None:
        mock_which.return_value = "/usr/local/bin/djinn-tlsn-verifier"
        assert is_available() is True

    @patch("djinn_validator.core.tlsn.shutil.which")
    @patch("djinn_validator.core.tlsn.os.path.isfile")
    def test_not_available(self, mock_isfile: MagicMock, mock_which: MagicMock) -> None:
        mock_which.return_value = None
        mock_isfile.return_value = False
        assert is_available() is False


class TestVerifyProof:
    """Test the TLSNotary verification subprocess call."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """Successful verification returns disclosed data."""
        verified_output = json.dumps(
            {
                "status": "verified",
                "server_name": "api.the-odds-api.com",
                "notary_key_alg": "secp256k1",
                "notary_key": "abcdef1234567890",
                "connection_time": "2026-02-15T12:00:00Z",
                "request": "GET /v4/sports/nba/odds",
                "response_body": '[{"id":"e1","bookmakers":[]}]',
                "response_full": 'HTTP/1.1 200 OK\r\n\r\n[{"id":"e1"}]',
            }
        ).encode()

        async def mock_subprocess(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 0

            async def communicate():
                return verified_output, b""

            proc.communicate = communicate
            return proc

        with patch(
            "djinn_validator.core.tlsn.asyncio.create_subprocess_exec",
            side_effect=mock_subprocess,
        ):
            result = await verify_proof(b"fake_presentation_bytes")

        assert result.verified is True
        assert result.server_name == "api.the-odds-api.com"
        assert "e1" in result.response_body

    @pytest.mark.asyncio
    async def test_verification_failure(self) -> None:
        """Failed verification returns error."""
        failure_output = json.dumps(
            {
                "status": "failed",
                "error": "invalid signature",
            }
        ).encode()

        async def mock_subprocess(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 1

            async def communicate():
                return failure_output, b""

            proc.communicate = communicate
            return proc

        with patch(
            "djinn_validator.core.tlsn.asyncio.create_subprocess_exec",
            side_effect=mock_subprocess,
        ):
            result = await verify_proof(b"bad_proof")

        assert result.verified is False
        assert "invalid signature" in result.error

    @pytest.mark.asyncio
    async def test_server_mismatch(self) -> None:
        """Server name mismatch is caught."""
        output = json.dumps(
            {
                "status": "verified",
                "server_name": "evil.example.com",
                "connection_time": "2026-02-15T12:00:00Z",
                "response_body": "fake data",
                "notary_key": "abc",
            }
        ).encode()

        async def mock_subprocess(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 0

            async def communicate():
                return output, b""

            proc.communicate = communicate
            return proc

        with patch(
            "djinn_validator.core.tlsn.asyncio.create_subprocess_exec",
            side_effect=mock_subprocess,
        ):
            result = await verify_proof(b"proof", expected_server="api.the-odds-api.com")

        assert result.verified is False
        assert "server mismatch" in result.error

    @pytest.mark.asyncio
    async def test_binary_not_found(self) -> None:
        """Missing verifier binary returns graceful error."""
        with patch(
            "djinn_validator.core.tlsn.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError,
        ):
            result = await verify_proof(b"proof")

        assert result.verified is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """Timeout returns graceful error."""
        with patch(
            "djinn_validator.core.tlsn.asyncio.create_subprocess_exec",
        ) as mock_exec:
            proc = MagicMock()
            # Use MagicMock (not AsyncMock) for communicate — the mocked
            # wait_for raises TimeoutError before awaiting the coroutine,
            # so an AsyncMock would create an unawaited coroutine warning.
            proc.communicate = MagicMock()
            mock_exec.return_value = proc

            with patch(
                "djinn_validator.core.tlsn.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ):
                result = await verify_proof(b"proof", timeout=0.1)

        assert result.verified is False
        assert "timed out" in result.error


class TestNotaryKeyValidation:
    """Test TRUSTED_NOTARY_KEYS hex validation regex."""

    def test_valid_64_char_hex_accepted(self) -> None:
        key = "a" * 64
        assert _HEX_KEY_RE.match(key) is not None

    def test_valid_130_char_hex_accepted(self) -> None:
        key = "0" * 130
        assert _HEX_KEY_RE.match(key) is not None

    def test_short_hex_rejected(self) -> None:
        key = "abcdef"
        assert _HEX_KEY_RE.match(key) is None

    def test_non_hex_rejected(self) -> None:
        key = "g" * 64
        assert _HEX_KEY_RE.match(key) is None

    def test_spaces_rejected(self) -> None:
        key = " " * 64
        assert _HEX_KEY_RE.match(key) is None

    def test_mixed_case_hex_accepted(self) -> None:
        key = "aAbBcCdDeEfF" * 6  # 72 chars
        assert _HEX_KEY_RE.match(key) is not None
