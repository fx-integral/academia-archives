"""Tests for POST /v1/notary/session endpoint with burn-gate auth."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.challenges import PeerNotary
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


BURN_AUTH_HEADERS = {
    "X-Coldkey": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
    "X-Burn-Tx": "0xabc123def456",
    "X-Signature": "0x" + "aa" * 64,
}


def _mock_auth_success(coldkey: str, tx_hash: str, sig: str, substrate: object) -> tuple[bool, str]:
    return True, ""


def _mock_auth_fail(coldkey: str, tx_hash: str, sig: str, substrate: object) -> tuple[bool, str]:
    return False, "Invalid signature"


@pytest.fixture
def mock_neuron() -> MagicMock:
    neuron = MagicMock()
    neuron.metagraph = MagicMock()
    neuron.metagraph.coldkeys = ["cold_validator", "cold_operator_A", "cold_operator_B", "cold_operator_A"]
    neuron.uid = 0
    neuron.wallet = None
    neuron.subtensor = MagicMock()
    neuron.subtensor.substrate = MagicMock()
    neuron.get_miner_uids.return_value = [1, 2, 3]
    neuron.get_axon_info.side_effect = lambda uid: {
        1: {"ip": "1.2.3.4", "port": 8422, "hotkey": "hotkey_1"},
        2: {"ip": "5.6.7.8", "port": 8422, "hotkey": "hotkey_2"},
        3: {"ip": "9.10.11.12", "port": 8422, "hotkey": "hotkey_3"},
    }[uid]
    return neuron


@pytest.fixture
def client(mock_neuron: MagicMock) -> TestClient:
    share_store = ShareStore()
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor()
    app = create_app(
        share_store,
        purchase_orch,
        outcome_attestor,
        neuron=mock_neuron,
    )
    return TestClient(app)


SAMPLE_NOTARIES = [
    PeerNotary(uid=1, ip="1.2.3.4", port=8422, notary_port=7047, pubkey_hex="02" + "ab" * 32),
    PeerNotary(uid=2, ip="5.6.7.8", port=8422, notary_port=7047, pubkey_hex="02" + "cd" * 32),
]


class TestBurnGateAuth:
    """Burn-gate authentication tests."""

    def test_missing_headers(self, client: TestClient) -> None:
        resp = client.post("/v1/notary/session")
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"]

    def test_missing_coldkey(self, client: TestClient) -> None:
        headers = {k: v for k, v in BURN_AUTH_HEADERS.items() if k != "X-Coldkey"}
        resp = client.post("/v1/notary/session", headers=headers)
        assert resp.status_code == 401

    def test_missing_tx_hash(self, client: TestClient) -> None:
        headers = {k: v for k, v in BURN_AUTH_HEADERS.items() if k != "X-Burn-Tx"}
        resp = client.post("/v1/notary/session", headers=headers)
        assert resp.status_code == 401

    def test_missing_signature(self, client: TestClient) -> None:
        headers = {k: v for k, v in BURN_AUTH_HEADERS.items() if k != "X-Signature"}
        resp = client.post("/v1/notary/session", headers=headers)
        assert resp.status_code == 401

    def test_invalid_signature(self, client: TestClient) -> None:
        with patch("djinn_validator.api.burn_gate.authenticate_request", side_effect=_mock_auth_fail):
            resp = client.post("/v1/notary/session", headers=BURN_AUTH_HEADERS)
        assert resp.status_code == 401
        assert "Invalid signature" in resp.json()["detail"]

    @patch(
        "djinn_validator.core.challenges.discover_peer_notaries",
        new_callable=AsyncMock,
        return_value=SAMPLE_NOTARIES,
    )
    def test_valid_burn_auth(self, mock_discover: AsyncMock, client: TestClient) -> None:
        with patch("djinn_validator.api.burn_gate.authenticate_request", side_effect=_mock_auth_success):
            resp = client.post("/v1/notary/session", headers=BURN_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["miner_port"] == 8422


class TestNotarySessionAssignment:
    """Miner assignment tests (with mocked auth)."""

    def _authed_post(self, client: TestClient, **kwargs: object) -> object:
        with patch("djinn_validator.api.burn_gate.authenticate_request", side_effect=_mock_auth_success):
            return client.post(
                "/v1/notary/session",
                headers=BURN_AUTH_HEADERS,
                **kwargs,
            )

    @patch(
        "djinn_validator.core.challenges.discover_peer_notaries",
        new_callable=AsyncMock,
        return_value=SAMPLE_NOTARIES,
    )
    def test_success(self, mock_discover: AsyncMock, client: TestClient) -> None:
        resp = self._authed_post(client)
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["miner_port"] == 8422
        assert data["miner_ws_path"] == "/v1/notary/ws"
        assert data["notary_public_key"].startswith("02")
        assert data["miner_hotkey"] in ("hotkey_1", "hotkey_2", "hotkey_3")
        assert data["expires_at"] > int(time.time())

    @patch(
        "djinn_validator.core.challenges.discover_peer_notaries",
        new_callable=AsyncMock,
        return_value=[],
    )
    def test_no_notary_sidecars(self, mock_discover: AsyncMock, client: TestClient) -> None:
        resp = self._authed_post(client)
        assert resp.status_code == 503
        assert "notary" in resp.json()["detail"].lower()

    def test_no_neuron(self) -> None:
        share_store = ShareStore()
        purchase_orch = PurchaseOrchestrator(share_store)
        outcome_attestor = OutcomeAttestor()
        app = create_app(share_store, purchase_orch, outcome_attestor, neuron=None)
        no_neuron_client = TestClient(app)

        with patch("djinn_validator.api.burn_gate.authenticate_request", side_effect=_mock_auth_success):
            resp = no_neuron_client.post(
                "/v1/notary/session",
                headers=BURN_AUTH_HEADERS,
            )
        assert resp.status_code == 503
        assert "network" in resp.json()["detail"].lower()

    def test_no_miners(self, client: TestClient, mock_neuron: MagicMock) -> None:
        mock_neuron.get_miner_uids.return_value = []
        resp = self._authed_post(client)
        assert resp.status_code == 503

    @patch(
        "djinn_validator.core.challenges.discover_peer_notaries",
        new_callable=AsyncMock,
        return_value=SAMPLE_NOTARIES,
    )
    def test_response_has_miner_hotkey(self, mock_discover: AsyncMock, client: TestClient) -> None:
        resp = self._authed_post(client)
        data = resp.json()
        chosen_ip = data["miner_ip"]
        if chosen_ip == "1.2.3.4":
            assert data["miner_hotkey"] == "hotkey_1"
        elif chosen_ip == "5.6.7.8":
            assert data["miner_hotkey"] == "hotkey_2"


class TestNotarySessionExclusions:
    """Miner exclusion and dedup tests."""

    def _authed_post(self, client: TestClient, **kwargs: object) -> object:
        with patch("djinn_validator.api.burn_gate.authenticate_request", side_effect=_mock_auth_success):
            return client.post(
                "/v1/notary/session",
                headers=BURN_AUTH_HEADERS,
                **kwargs,
            )

    @patch(
        "djinn_validator.core.challenges.discover_peer_notaries",
        new_callable=AsyncMock,
        return_value=SAMPLE_NOTARIES,
    )
    def test_no_exclusions_uses_all_miners(self, mock_discover: AsyncMock, client: TestClient) -> None:
        resp = self._authed_post(client)
        assert resp.status_code == 200
        called_axons = mock_discover.call_args[0][1]
        assert len(called_axons) == 3

    @patch(
        "djinn_validator.core.challenges.discover_peer_notaries",
        new_callable=AsyncMock,
        return_value=[SAMPLE_NOTARIES[1]],
    )
    def test_exclude_miners_request_body_dedup(self, mock_discover: AsyncMock, client: TestClient) -> None:
        resp = self._authed_post(client, json={"exclude_miners": ["hotkey_1", "hotkey_3"]})
        assert resp.status_code == 200
        called_axons = mock_discover.call_args[0][1]
        hotkeys_sent = {a["hotkey"] for a in called_axons}
        assert "hotkey_1" not in hotkeys_sent
        assert "hotkey_3" not in hotkeys_sent
        assert "hotkey_2" in hotkeys_sent

    @patch(
        "djinn_validator.core.challenges.discover_peer_notaries",
        new_callable=AsyncMock,
        return_value=[SAMPLE_NOTARIES[1]],
    )
    def test_exclude_ips_dedup(self, mock_discover: AsyncMock, client: TestClient) -> None:
        resp = self._authed_post(client, json={"exclude_ips": ["1.2.3.4", "9.10.11.12"]})
        assert resp.status_code == 200
        called_axons = mock_discover.call_args[0][1]
        ips_sent = {a["ip"] for a in called_axons}
        assert "1.2.3.4" not in ips_sent
        assert "9.10.11.12" not in ips_sent
        assert "5.6.7.8" in ips_sent

    def test_exclude_all_miners_returns_503(self, client: TestClient) -> None:
        resp = self._authed_post(client, json={"exclude_miners": ["hotkey_1", "hotkey_2", "hotkey_3"]})
        assert resp.status_code == 503
        assert "exclusion" in resp.json()["detail"].lower()


class TestBurnGateUnit:
    """Unit tests for burn_gate module functions."""

    def test_verify_signature_bad_coldkey(self) -> None:
        from djinn_validator.api.burn_gate import verify_signature

        assert verify_signature("not_an_ss58", "abcd", "ee" * 64) is False

    def test_cache_eviction(self) -> None:
        from djinn_validator.api.burn_gate import _cache, _cache_set, CACHE_TTL_VALID_SECONDS

        _cache.clear()
        old_ts = time.time() - CACHE_TTL_VALID_SECONDS - 10
        for i in range(1010):
            _cache[f"tx_{i}"] = {"valid": True, "error": "", "coldkey": "x", "block_ts": 0, "checked_at": old_ts}
        _cache_set("tx_new", {"valid": True, "error": "", "coldkey": "x", "block_ts": 0})
        assert len(_cache) <= 2

    def test_authenticate_missing_fields(self) -> None:
        from djinn_validator.api.burn_gate import authenticate_request

        valid, err = authenticate_request("", "", "", None)
        assert not valid
        assert "Missing" in err

    def test_verify_burn_tx_caches_result(self) -> None:
        from djinn_validator.api.burn_gate import _cache, _cache_set, verify_burn_tx

        _cache.clear()
        import time as _t

        _cache_set(
            "0xtest123",
            {
                "valid": True,
                "error": "",
                "coldkey": "5GoodColdkey",
                "amount": 2.0,
                "block_ts": _t.time() - 100,
            },
        )
        valid, err = verify_burn_tx("0xtest123", "5GoodColdkey", None)
        assert valid
        assert err == ""

    def test_verify_burn_tx_cached_wrong_coldkey(self) -> None:
        from djinn_validator.api.burn_gate import _cache, _cache_set, verify_burn_tx

        _cache.clear()
        import time as _t

        _cache_set(
            "0xtest456",
            {
                "valid": True,
                "error": "",
                "coldkey": "5GoodColdkey",
                "amount": 2.0,
                "block_ts": _t.time() - 100,
            },
        )
        valid, err = verify_burn_tx("0xtest456", "5DifferentColdkey", None)
        assert not valid
        assert "coldkey" in err.lower()

    def test_verify_burn_tx_cached_expired(self) -> None:
        from djinn_validator.api.burn_gate import _cache, _cache_set, verify_burn_tx, BURN_WINDOW_SECONDS

        _cache.clear()
        import time as _t

        _cache_set(
            "0xold789",
            {
                "valid": True,
                "error": "",
                "coldkey": "5GoodColdkey",
                "amount": 2.0,
                "block_ts": _t.time() - BURN_WINDOW_SECONDS - 100,
            },
        )
        valid, err = verify_burn_tx("0xold789", "5GoodColdkey", None)
        assert not valid
        assert "old" in err.lower()


class TestBurnVerifyEndpoint:
    """Tests for GET /v1/burn/verify peer cache endpoint.

    The TestClient reports a ``client.host`` of ``"testclient"`` which the
    P1-26 IP allowlist (added 2026-04-18) would reject. We patch the
    allowlist check to return True so these tests keep exercising the
    cache/signing logic rather than the transport gate.
    """

    @pytest.fixture(autouse=True)
    def _bypass_ip_allowlist(self):
        with patch(
            "djinn_validator.api.burn_gate.is_allowed_peer_ip",
            return_value=True,
        ):
            yield

    def test_valid_cached_burn(self, client: TestClient) -> None:
        from djinn_validator.api.burn_gate import _cache, _cache_set

        _cache.clear()
        import time as _t

        _cache_set(
            "0xpeertx",
            {
                "valid": True,
                "error": "",
                "coldkey": "5PeerColdkey",
                "amount": 2.0,
                "block_ts": _t.time() - 100,
            },
        )
        resp = client.get("/v1/burn/verify", params={"tx_hash": "0xpeertx", "coldkey": "5PeerColdkey"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["amount"] == 2.0

    def test_unknown_tx(self, client: TestClient) -> None:
        from djinn_validator.api.burn_gate import _cache

        _cache.clear()
        resp = client.get("/v1/burn/verify", params={"tx_hash": "0xunknown", "coldkey": "5Someone"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_wrong_coldkey(self, client: TestClient) -> None:
        from djinn_validator.api.burn_gate import _cache, _cache_set

        _cache.clear()
        import time as _t

        _cache_set(
            "0xpeertx2",
            {
                "valid": True,
                "error": "",
                "coldkey": "5RealColdkey",
                "amount": 1.5,
                "block_ts": _t.time() - 100,
            },
        )
        resp = client.get("/v1/burn/verify", params={"tx_hash": "0xpeertx2", "coldkey": "5WrongColdkey"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_missing_params(self, client: TestClient) -> None:
        resp = client.get("/v1/burn/verify")
        assert resp.status_code == 400


class TestBurnPeerResponseSigning:
    """P1-21: verify burn-peer responses are hotkey-signed and authenticated."""

    def _make_wallet(self) -> tuple[object, str]:
        import bittensor as bt

        keypair = bt.Keypair.create_from_uri("//PeerAlice")
        wallet = MagicMock()
        wallet.hotkey = keypair
        return wallet, keypair.ss58_address

    def test_sign_peer_response_verifies(self) -> None:
        """A signed response can be verified by anyone with the hotkey set."""
        from djinn_validator.api.burn_gate import (
            sign_peer_response,
            _verify_peer_response,
        )

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        ok, err = _verify_peer_response(
            data,
            expected_tx_hash="0xabc",
            expected_coldkey="5Cold",
            allowed_hotkeys={hotkey},
        )
        assert ok, err
        assert err == ""

    def test_unsigned_response_rejected(self) -> None:
        from djinn_validator.api.burn_gate import _verify_peer_response

        data = {"valid": True, "amount": 1.0, "block_ts": time.time()}
        ok, err = _verify_peer_response(data, "0xabc", "5Cold", {"5SomeHotkey"})
        assert not ok
        assert "unsigned" in err.lower()

    def test_signer_not_in_metagraph_rejected(self) -> None:
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        ok, err = _verify_peer_response(data, "0xabc", "5Cold", allowed_hotkeys={"5OtherHotkey"})
        assert not ok
        assert "not a registered validator" in err

    def test_mismatched_tx_hash_rejected(self) -> None:
        """Signature over tx_hash=X cannot confirm tx_hash=Y even if both valid."""
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        ok, err = _verify_peer_response(data, "0xDIFFERENT", "5Cold", allowed_hotkeys={hotkey})
        assert not ok
        assert "tx_hash mismatch" in err

    def test_tampered_amount_breaks_signature(self) -> None:
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        data["amount"] = 999.0  # attacker bumps amount without re-signing
        ok, err = _verify_peer_response(data, "0xabc", "5Cold", allowed_hotkeys={hotkey})
        assert not ok
        assert "invalid signature" in err

    def test_stale_response_rejected(self) -> None:
        from djinn_validator.api.burn_gate import (
            sign_peer_response,
            _verify_peer_response,
            PEER_RESPONSE_MAX_AGE_S,
        )

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        # Backdate the response_ts beyond the acceptance window
        data["response_ts"] = int(time.time()) - (PEER_RESPONSE_MAX_AGE_S + 60)
        ok, err = _verify_peer_response(data, "0xabc", "5Cold", allowed_hotkeys={hotkey})
        assert not ok
        assert "stale" in err.lower()

    @pytest.mark.asyncio
    async def test_verify_burn_via_peers_requires_quorum_of_distinct_hotkeys(self) -> None:
        """Same peer responding twice must not count as two confirmations."""
        from unittest.mock import AsyncMock
        from djinn_validator.api import burn_gate
        import bittensor as bt

        peer_kp = bt.Keypair.create_from_uri("//OnePeer")
        peer_wallet = MagicMock()
        peer_wallet.hotkey = peer_kp
        signed = burn_gate.sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=peer_kp.ss58_address,
            wallet=peer_wallet,
        )

        class _Resp:
            status_code = 200

            def __init__(self, d: dict) -> None:
                self._d = d

            def json(self) -> dict:
                return self._d

        async def _fake_get(self: object, url: str, params: dict) -> _Resp:
            return _Resp(signed)

        burn_gate._cache.clear()
        with patch("httpx.AsyncClient.get", new=_fake_get):
            ok, err = await burn_gate.verify_burn_via_peers(
                "0xabc",
                "5Cold",
                ["http://10.0.0.1:8421", "http://10.0.0.2:8421"],
                allowed_hotkeys={peer_kp.ss58_address},
            )
        assert not ok
        assert "1 signed peer" in err or "need 2" in err

    @pytest.mark.asyncio
    async def test_verify_burn_via_peers_accepts_two_distinct_signers(self) -> None:
        from unittest.mock import AsyncMock
        from djinn_validator.api import burn_gate
        import bittensor as bt

        peer_a_kp = bt.Keypair.create_from_uri("//PeerA")
        peer_b_kp = bt.Keypair.create_from_uri("//PeerB")
        wa, wb = MagicMock(), MagicMock()
        wa.hotkey, wb.hotkey = peer_a_kp, peer_b_kp
        signed_a = burn_gate.sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=peer_a_kp.ss58_address,
            wallet=wa,
        )
        signed_b = burn_gate.sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=peer_b_kp.ss58_address,
            wallet=wb,
        )

        responses = iter([signed_a, signed_b])

        class _Resp:
            status_code = 200

            def __init__(self, d: dict) -> None:
                self._d = d

            def json(self) -> dict:
                return self._d

        async def _fake_get(self: object, url: str, params: dict) -> _Resp:
            return _Resp(next(responses))

        burn_gate._cache.clear()
        with patch("httpx.AsyncClient.get", new=_fake_get):
            ok, err = await burn_gate.verify_burn_via_peers(
                "0xabc",
                "5Cold",
                ["http://10.0.0.1:8421", "http://10.0.0.2:8421"],
                allowed_hotkeys={peer_a_kp.ss58_address, peer_b_kp.ss58_address},
            )
        assert ok, err
        assert err == ""

    @pytest.mark.asyncio
    async def test_verify_burn_via_peers_rejects_when_no_hotkey_set(self) -> None:
        """Without metagraph context we fail closed (no trusted-peer fallback)."""
        from djinn_validator.api import burn_gate

        ok, err = await burn_gate.verify_burn_via_peers(
            "0xabc",
            "5Cold",
            ["http://10.0.0.1:8421"],
            allowed_hotkeys=None,
        )
        assert not ok
        assert "no metagraph context" in err.lower()

    @pytest.mark.asyncio
    async def test_verify_burn_via_peers_rejects_block_ts_disagreement(self) -> None:
        """A malicious-but-authorized signer cannot poison block_ts cache.

        If two signers disagree on block_ts beyond one-block tolerance (~12s),
        no quorum forms. A legitimate on-chain burn has a single block_ts;
        divergence means at least one signer is attempting to poison the
        local cache (extending burn validity by reporting future-dated ts).
        """
        from unittest.mock import AsyncMock
        from djinn_validator.api import burn_gate
        import bittensor as bt

        peer_a_kp = bt.Keypair.create_from_uri("//PeerDisA")
        peer_b_kp = bt.Keypair.create_from_uri("//PeerDisB")
        wa, wb = MagicMock(), MagicMock()
        wa.hotkey, wb.hotkey = peer_a_kp, peer_b_kp
        now = time.time()
        signed_a = burn_gate.sign_peer_response(
            tx_hash="0xdis",
            coldkey="5ColdDis",
            valid=True,
            amount=2.0,
            block_ts=now,
            signer_hotkey=peer_a_kp.ss58_address,
            wallet=wa,
        )
        # peer B reports block_ts 1 hour in the future (poisoning attempt)
        signed_b = burn_gate.sign_peer_response(
            tx_hash="0xdis",
            coldkey="5ColdDis",
            valid=True,
            amount=2.0,
            block_ts=now + 3600,
            signer_hotkey=peer_b_kp.ss58_address,
            wallet=wb,
        )

        responses = iter([signed_a, signed_b])

        class _Resp:
            status_code = 200

            def __init__(self, d: dict) -> None:
                self._d = d

            def json(self) -> dict:
                return self._d

        async def _fake_get(self: object, url: str, params: dict) -> _Resp:
            return _Resp(next(responses))

        burn_gate._cache.clear()
        with patch("httpx.AsyncClient.get", new=_fake_get):
            ok, err = await burn_gate.verify_burn_via_peers(
                "0xdis",
                "5ColdDis",
                ["http://10.0.0.1:8421", "http://10.0.0.2:8421"],
                allowed_hotkeys={peer_a_kp.ss58_address, peer_b_kp.ss58_address},
            )
        assert not ok
        # B's disagreeing block_ts was rejected; only A's hotkey contributes. Need 2, got 1.
        assert "1 signed peer" in err or "Only 1" in err

    @pytest.mark.asyncio
    async def test_verify_burn_via_peers_rejects_amount_disagreement(self) -> None:
        """A malicious-but-authorized signer cannot poison amount cache."""
        from unittest.mock import AsyncMock
        from djinn_validator.api import burn_gate
        import bittensor as bt

        peer_a_kp = bt.Keypair.create_from_uri("//PeerAmtA")
        peer_b_kp = bt.Keypair.create_from_uri("//PeerAmtB")
        wa, wb = MagicMock(), MagicMock()
        wa.hotkey, wb.hotkey = peer_a_kp, peer_b_kp
        now = time.time()
        signed_a = burn_gate.sign_peer_response(
            tx_hash="0xamt",
            coldkey="5ColdAmt",
            valid=True,
            amount=2.0,
            block_ts=now,
            signer_hotkey=peer_a_kp.ss58_address,
            wallet=wa,
        )
        # peer B reports a different amount for the same (tx_hash, coldkey)
        signed_b = burn_gate.sign_peer_response(
            tx_hash="0xamt",
            coldkey="5ColdAmt",
            valid=True,
            amount=999.0,
            block_ts=now,
            signer_hotkey=peer_b_kp.ss58_address,
            wallet=wb,
        )

        responses = iter([signed_a, signed_b])

        class _Resp:
            status_code = 200

            def __init__(self, d: dict) -> None:
                self._d = d

            def json(self) -> dict:
                return self._d

        async def _fake_get(self: object, url: str, params: dict) -> _Resp:
            return _Resp(next(responses))

        burn_gate._cache.clear()
        with patch("httpx.AsyncClient.get", new=_fake_get):
            ok, err = await burn_gate.verify_burn_via_peers(
                "0xamt",
                "5ColdAmt",
                ["http://10.0.0.1:8421", "http://10.0.0.2:8421"],
                allowed_hotkeys={peer_a_kp.ss58_address, peer_b_kp.ss58_address},
            )
        assert not ok
        assert "1 signed peer" in err or "Only 1" in err

    # ------------------------------------------------------------------
    # P1-25: recipient-hotkey binding (cross-validator replay defense)
    # ------------------------------------------------------------------

    def test_sign_peer_response_includes_recipient_hotkey_when_provided(self) -> None:
        """When the peer is told who it is signing for, that hotkey is in payload."""
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
            recipient_hotkey="5Recipient",
        )
        assert data["recipient_hotkey"] == "5Recipient"
        ok, err = _verify_peer_response(
            data,
            "0xabc",
            "5Cold",
            {hotkey},
            expected_recipient_hotkey="5Recipient",
        )
        assert ok, err

    def test_replay_to_different_recipient_rejected(self) -> None:
        """A response signed for validator X cannot be verified by validator Y.

        This is the heart of P1-25: even if an attacker captures a
        legitimate signed response, replaying it to a different validator
        fails recipient_hotkey equality.
        """
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
            recipient_hotkey="5Alice",
        )
        # Bob receives a response originally signed for Alice
        ok, err = _verify_peer_response(
            data,
            "0xabc",
            "5Cold",
            {hotkey},
            expected_recipient_hotkey="5Bob",
        )
        assert not ok
        assert "recipient_hotkey mismatch" in err

    def test_tampered_recipient_breaks_signature(self) -> None:
        """Rewriting recipient_hotkey without re-signing invalidates signature."""
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
            recipient_hotkey="5Alice",
        )
        # Attacker rewrites recipient to match their own hotkey, hoping
        # the verifier will accept it. Signature check must catch this.
        data["recipient_hotkey"] = "5Bob"
        ok, err = _verify_peer_response(
            data,
            "0xabc",
            "5Cold",
            {hotkey},
            expected_recipient_hotkey="5Bob",
        )
        assert not ok
        assert "invalid signature" in err

    def test_legacy_unbound_response_still_accepted_during_rollout(self) -> None:
        """Old peers don't include recipient_hotkey; new requesters must still accept.

        Backward-compat for the mixed-version rollout window — until every
        validator upgrades, a new requester will sometimes talk to an old
        peer that doesn't know about recipient_hotkey. We accept the
        legacy unbound payload and fall back to the pre-P1-25 protection
        level (signer-hotkey check + stale/mismatch checks are still
        enforced). This branch should be removed after the network
        upgrades past the rollout — see P1-25 in MAINNET_BLOCKERS.md.
        """
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        # Sign the legacy way (no recipient_hotkey arg -> not in payload)
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        assert "recipient_hotkey" not in data
        # New verifier with expected_recipient_hotkey still accepts the
        # legacy-shape payload because the response itself has no field
        # to mismatch against.
        ok, err = _verify_peer_response(
            data,
            "0xabc",
            "5Cold",
            {hotkey},
            expected_recipient_hotkey="5Alice",
        )
        assert ok, err

    @pytest.mark.asyncio
    async def test_verify_burn_via_peers_sends_recipient_hotkey_query_param(self) -> None:
        """Requester must send its own hotkey as a query param for peer to bind."""
        from djinn_validator.api import burn_gate
        import bittensor as bt

        peer_a_kp = bt.Keypair.create_from_uri("//PeerRcpA")
        peer_b_kp = bt.Keypair.create_from_uri("//PeerRcpB")
        wa, wb = MagicMock(), MagicMock()
        wa.hotkey, wb.hotkey = peer_a_kp, peer_b_kp
        requester_hotkey = "5RequesterValidator"
        signed_a = burn_gate.sign_peer_response(
            tx_hash="0xrcp",
            coldkey="5ColdRcp",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=peer_a_kp.ss58_address,
            wallet=wa,
            recipient_hotkey=requester_hotkey,
        )
        signed_b = burn_gate.sign_peer_response(
            tx_hash="0xrcp",
            coldkey="5ColdRcp",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=peer_b_kp.ss58_address,
            wallet=wb,
            recipient_hotkey=requester_hotkey,
        )

        responses = iter([signed_a, signed_b])
        seen_params: list[dict] = []

        class _Resp:
            status_code = 200

            def __init__(self, d: dict) -> None:
                self._d = d

            def json(self) -> dict:
                return self._d

        async def _fake_get(self: object, url: str, params: dict) -> _Resp:
            seen_params.append(params)
            return _Resp(next(responses))

        burn_gate._cache.clear()
        with patch("httpx.AsyncClient.get", new=_fake_get):
            ok, err = await burn_gate.verify_burn_via_peers(
                "0xrcp",
                "5ColdRcp",
                ["http://10.0.0.1:8421", "http://10.0.0.2:8421"],
                allowed_hotkeys={peer_a_kp.ss58_address, peer_b_kp.ss58_address},
                self_hotkey=requester_hotkey,
            )
        assert ok, err
        # Both peers received recipient_hotkey in the query
        for p in seen_params:
            assert p.get("recipient_hotkey") == requester_hotkey

    @pytest.mark.asyncio
    async def test_verify_burn_via_peers_rejects_response_bound_to_other_recipient(self) -> None:
        """If a peer's response is bound to a different recipient, quorum does not form.

        Simulates an attacker-captured signed response originally destined
        for validator X being replayed to validator Y.
        """
        from djinn_validator.api import burn_gate
        import bittensor as bt

        peer_a_kp = bt.Keypair.create_from_uri("//PeerReplayA")
        peer_b_kp = bt.Keypair.create_from_uri("//PeerReplayB")
        wa, wb = MagicMock(), MagicMock()
        wa.hotkey, wb.hotkey = peer_a_kp, peer_b_kp
        # Both responses are bound to validator X
        signed_a = burn_gate.sign_peer_response(
            tx_hash="0xrpl",
            coldkey="5ColdRpl",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=peer_a_kp.ss58_address,
            wallet=wa,
            recipient_hotkey="5ValidatorX",
        )
        signed_b = burn_gate.sign_peer_response(
            tx_hash="0xrpl",
            coldkey="5ColdRpl",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=peer_b_kp.ss58_address,
            wallet=wb,
            recipient_hotkey="5ValidatorX",
        )

        responses = iter([signed_a, signed_b])

        class _Resp:
            status_code = 200

            def __init__(self, d: dict) -> None:
                self._d = d

            def json(self) -> dict:
                return self._d

        async def _fake_get(self: object, url: str, params: dict) -> _Resp:
            return _Resp(next(responses))

        burn_gate._cache.clear()
        with patch("httpx.AsyncClient.get", new=_fake_get):
            # Validator Y asks the same peers — captures replay attempt
            ok, err = await burn_gate.verify_burn_via_peers(
                "0xrpl",
                "5ColdRpl",
                ["http://10.0.0.1:8421", "http://10.0.0.2:8421"],
                allowed_hotkeys={peer_a_kp.ss58_address, peer_b_kp.ss58_address},
                self_hotkey="5ValidatorY",
            )
        assert not ok
        # No signer qualified — every response was bound to X, Y receives them
        assert "No peer validators could verify" in err or "0 signed peer" in err

    # ------------------------------------------------------------------
    # P1-25 hardening: DJINN_BURN_GATE_STRICT_RECIPIENT
    # Fresh-eyes audit on v1267 flagged HIGH: legacy-acceptance branch
    # leaves the replay window open indefinitely with no flip trigger.
    # The env flag gives operators an opt-in to reject legacy unbound
    # responses once the network has fully rolled forward past v1267.
    # ------------------------------------------------------------------

    def test_strict_mode_rejects_legacy_unbound_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With DJINN_BURN_GATE_STRICT_RECIPIENT=1, legacy payloads are rejected."""
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        assert "recipient_hotkey" not in data

        monkeypatch.setenv("DJINN_BURN_GATE_STRICT_RECIPIENT", "1")
        ok, err = _verify_peer_response(
            data,
            "0xabc",
            "5Cold",
            {hotkey},
            expected_recipient_hotkey="5Alice",
        )
        assert not ok
        assert "missing recipient_hotkey" in err
        assert "strict mode" in err

    def test_strict_mode_accepts_bound_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Strict mode still accepts a correctly-bound v1267+ response."""
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
            recipient_hotkey="5Alice",
        )
        monkeypatch.setenv("DJINN_BURN_GATE_STRICT_RECIPIENT", "1")
        ok, err = _verify_peer_response(
            data,
            "0xabc",
            "5Cold",
            {hotkey},
            expected_recipient_hotkey="5Alice",
        )
        assert ok, err

    def test_non_strict_mode_still_accepts_legacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default (flag unset or falsy) preserves mixed-version rollout acceptance."""
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        # Explicitly unset the flag to guard against test-env leakage.
        monkeypatch.delenv("DJINN_BURN_GATE_STRICT_RECIPIENT", raising=False)
        ok, err = _verify_peer_response(
            data,
            "0xabc",
            "5Cold",
            {hotkey},
            expected_recipient_hotkey="5Alice",
        )
        assert ok, err

        # Also check falsy values explicitly
        for falsy in ("", "0", "false", "no", "FALSE"):
            monkeypatch.setenv("DJINN_BURN_GATE_STRICT_RECIPIENT", falsy)
            ok, err = _verify_peer_response(
                data,
                "0xabc",
                "5Cold",
                {hotkey},
                expected_recipient_hotkey="5Alice",
            )
            assert ok, f"flag={falsy!r} should be non-strict: err={err}"

    def test_strict_mode_accepts_legacy_when_no_expected_recipient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No self_hotkey provided = no binding expected = strict is a no-op.

        Protects against a validator that hasn't configured its own hotkey
        into the call chain yet — we don't gratuitously reject responses
        the caller wasn't asking to bind.
        """
        from djinn_validator.api.burn_gate import sign_peer_response, _verify_peer_response

        wallet, hotkey = self._make_wallet()
        data = sign_peer_response(
            tx_hash="0xabc",
            coldkey="5Cold",
            valid=True,
            amount=2.0,
            block_ts=time.time(),
            signer_hotkey=hotkey,
            wallet=wallet,
        )
        monkeypatch.setenv("DJINN_BURN_GATE_STRICT_RECIPIENT", "1")
        ok, err = _verify_peer_response(
            data,
            "0xabc",
            "5Cold",
            {hotkey},
            expected_recipient_hotkey="",  # caller doesn't know its own hotkey
        )
        assert ok, err


class TestBurnVerifyIPAllowlist:
    """P1-26: /v1/burn/verify source IP must map to a registered validator."""

    def _make_metagraph(self, validator_ips: list[str]) -> MagicMock:
        """Build a metagraph mock with N registered validators at the given IPs."""
        mg = MagicMock()
        mg.n = MagicMock()
        mg.n.item.return_value = len(validator_ips)
        mg.validator_permit = [MagicMock(item=MagicMock(return_value=True)) for _ in validator_ips]
        mg.axons = []
        for ip in validator_ips:
            axon = MagicMock()
            axon.ip = ip
            mg.axons.append(axon)
        return mg

    def test_helper_allows_localhost(self) -> None:
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        neuron = MagicMock()
        neuron.metagraph = self._make_metagraph(["9.9.9.9"])
        assert is_allowed_peer_ip(neuron, "127.0.0.1")
        assert is_allowed_peer_ip(neuron, "::1")
        assert is_allowed_peer_ip(neuron, "localhost")

    def test_helper_allows_registered_validator_ip(self) -> None:
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        neuron = MagicMock()
        neuron.metagraph = self._make_metagraph(["1.2.3.4", "5.6.7.8"])
        assert is_allowed_peer_ip(neuron, "1.2.3.4")
        assert is_allowed_peer_ip(neuron, "5.6.7.8")

    def test_helper_rejects_unknown_ip(self) -> None:
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        neuron = MagicMock()
        neuron.metagraph = self._make_metagraph(["1.2.3.4"])
        assert not is_allowed_peer_ip(neuron, "99.99.99.99")

    def test_helper_rejects_non_validator_neuron(self) -> None:
        """A neuron IP that is present but lacks validator_permit must be rejected."""
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        mg = MagicMock()
        mg.n = MagicMock()
        mg.n.item.return_value = 2
        permit_true = MagicMock()
        permit_true.item.return_value = True
        permit_false = MagicMock()
        permit_false.item.return_value = False
        mg.validator_permit = [permit_true, permit_false]
        axon_validator = MagicMock()
        axon_validator.ip = "1.1.1.1"
        axon_miner = MagicMock()
        axon_miner.ip = "2.2.2.2"
        mg.axons = [axon_validator, axon_miner]
        neuron = MagicMock()
        neuron.metagraph = mg
        assert is_allowed_peer_ip(neuron, "1.1.1.1")
        assert not is_allowed_peer_ip(neuron, "2.2.2.2")

    def test_helper_fail_open_when_neuron_none(self) -> None:
        """Pre-metagraph startup: allow rather than lock out."""
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        assert is_allowed_peer_ip(None, "9.9.9.9")

    def test_helper_fail_open_when_metagraph_none(self) -> None:
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        neuron = MagicMock()
        neuron.metagraph = None
        assert is_allowed_peer_ip(neuron, "9.9.9.9")

    def test_helper_fail_open_when_metagraph_read_raises(self) -> None:
        """Metagraph partially loaded / read error should not lock out peers."""
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        mg = MagicMock()
        mg.n = MagicMock()
        mg.n.item.side_effect = RuntimeError("metagraph not ready")
        neuron = MagicMock()
        neuron.metagraph = mg
        assert is_allowed_peer_ip(neuron, "9.9.9.9")

    def test_helper_env_override_allows_any(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        monkeypatch.setenv("DJINN_BURN_GATE_ALLOW_ANY_IP", "1")
        neuron = MagicMock()
        neuron.metagraph = self._make_metagraph(["1.2.3.4"])
        assert is_allowed_peer_ip(neuron, "99.99.99.99")

    def test_endpoint_rejects_when_helper_rejects(self, client: TestClient) -> None:
        """Integration: endpoint returns 403 when the allowlist check fails."""
        with patch(
            "djinn_validator.api.burn_gate.is_allowed_peer_ip",
            return_value=False,
        ):
            resp = client.get(
                "/v1/burn/verify",
                params={"tx_hash": "0xabc", "coldkey": "5Cold"},
            )
        assert resp.status_code == 403
        assert "registered validator" in resp.json()["detail"].lower()

    def test_endpoint_allows_when_helper_allows(self, client: TestClient) -> None:
        """Integration: endpoint reaches the cache check when the allowlist passes."""
        from djinn_validator.api.burn_gate import _cache

        _cache.clear()
        with patch(
            "djinn_validator.api.burn_gate.is_allowed_peer_ip",
            return_value=True,
        ):
            resp = client.get(
                "/v1/burn/verify",
                params={"tx_hash": "0xunknown", "coldkey": "5Someone"},
            )
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_helper_rejects_zero_ip_even_with_zero_axon(self) -> None:
        """Unpublished axon IP (0.0.0.0) must not match a 0.0.0.0 request.

        Operators frequently register axons without publishing an IP
        (resulting in a 0.0.0.0 placeholder). If an attacker (or a
        misconfigured reverse proxy) forwards 0.0.0.0 as the request
        IP, the allowlist must reject — empty-vs-empty is a false
        match, not a grant.
        """
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        neuron = MagicMock()
        neuron.metagraph = self._make_metagraph(["0.0.0.0", "1.2.3.4"])
        assert not is_allowed_peer_ip(neuron, "0.0.0.0")
        assert not is_allowed_peer_ip(neuron, "")

    def test_helper_rejects_empty_string_axon(self) -> None:
        """An axon with ip="" should be skipped rather than fuzzy-matching."""
        from djinn_validator.api.burn_gate import is_allowed_peer_ip

        mg = MagicMock()
        mg.n = MagicMock()
        mg.n.item.return_value = 1
        permit_true = MagicMock()
        permit_true.item.return_value = True
        mg.validator_permit = [permit_true]
        axon = MagicMock()
        axon.ip = ""
        mg.axons = [axon]
        neuron = MagicMock()
        neuron.metagraph = mg
        assert not is_allowed_peer_ip(neuron, "1.1.1.1")

    def test_helper_normalizes_ipv4_mapped_ipv6(self) -> None:
        """Peer on IPv6 listener with IPv4 traffic lands as ::ffff:a.b.c.d.

        The allowlist normalizes this to the IPv4 form so equality with
        the IPv4 axon entry in the metagraph still holds.
        """
        from djinn_validator.api.burn_gate import is_allowed_peer_ip, _normalize_ip

        assert _normalize_ip("::ffff:1.2.3.4") == "1.2.3.4"
        assert _normalize_ip("1.2.3.4") == "1.2.3.4"
        assert _normalize_ip("::1") == "::1"
        assert _normalize_ip("not-an-ip") == "not-an-ip"
        assert _normalize_ip("") == ""

        neuron = MagicMock()
        neuron.metagraph = self._make_metagraph(["1.2.3.4"])
        assert is_allowed_peer_ip(neuron, "::ffff:1.2.3.4")

    def test_endpoint_uses_real_helper_and_rejects(self, mock_neuron: MagicMock) -> None:
        """End-to-end: build an app where the helper is NOT patched and
        assert that the server-wiring actually calls it (guards against
        a regression where someone accidentally removes the call).

        TestClient presents client.host == "testclient" which the real
        helper normalizes (unparseable → passthrough) and then fails to
        find in the metagraph — so the endpoint must 403.
        """
        mock_neuron.metagraph.n = MagicMock()
        mock_neuron.metagraph.n.item.return_value = 1
        permit = MagicMock()
        permit.item.return_value = True
        mock_neuron.metagraph.validator_permit = [permit]
        axon = MagicMock()
        axon.ip = "9.9.9.9"
        mock_neuron.metagraph.axons = [axon]

        share_store = ShareStore()
        purchase_orch = PurchaseOrchestrator(share_store)
        outcome_attestor = OutcomeAttestor()
        app = create_app(
            share_store,
            purchase_orch,
            outcome_attestor,
            neuron=mock_neuron,
        )
        local_client = TestClient(app)
        resp = local_client.get(
            "/v1/burn/verify",
            params={"tx_hash": "0xabc", "coldkey": "5Cold"},
        )
        assert resp.status_code == 403

    def test_fail_open_counter_increments_on_missing_neuron(self) -> None:
        """Fail-open path bumps the Prometheus counter with reason=neuron_missing."""
        from djinn_validator.api.burn_gate import is_allowed_peer_ip
        from djinn_validator.api.metrics import BURN_GATE_FAIL_OPEN

        before = BURN_GATE_FAIL_OPEN.labels(reason="neuron_missing")._value.get()
        assert is_allowed_peer_ip(None, "9.9.9.9")
        after = BURN_GATE_FAIL_OPEN.labels(reason="neuron_missing")._value.get()
        assert after == before + 1

    def test_fail_open_counter_increments_on_missing_metagraph(self) -> None:
        """neuron present but metagraph=None → reason=metagraph_missing."""
        from djinn_validator.api.burn_gate import is_allowed_peer_ip
        from djinn_validator.api.metrics import BURN_GATE_FAIL_OPEN

        neuron = MagicMock()
        neuron.metagraph = None
        before = BURN_GATE_FAIL_OPEN.labels(reason="metagraph_missing")._value.get()
        assert is_allowed_peer_ip(neuron, "9.9.9.9")
        after = BURN_GATE_FAIL_OPEN.labels(reason="metagraph_missing")._value.get()
        assert after == before + 1

    def test_fail_open_counter_increments_on_metagraph_read_error(self) -> None:
        """Metagraph raises on .n.item() → reason=metagraph_read_error."""
        from djinn_validator.api.burn_gate import is_allowed_peer_ip
        from djinn_validator.api.metrics import BURN_GATE_FAIL_OPEN

        mg = MagicMock()
        mg.n = MagicMock()
        mg.n.item.side_effect = RuntimeError("metagraph not ready")
        neuron = MagicMock()
        neuron.metagraph = mg
        before = BURN_GATE_FAIL_OPEN.labels(reason="metagraph_read_error")._value.get()
        assert is_allowed_peer_ip(neuron, "9.9.9.9")
        after = BURN_GATE_FAIL_OPEN.labels(reason="metagraph_read_error")._value.get()
        assert after == before + 1

    def test_fail_open_counter_does_not_increment_on_normal_allow(self) -> None:
        """Localhost / permitted-IP / reject paths must NOT bump the counter."""
        from djinn_validator.api.burn_gate import is_allowed_peer_ip
        from djinn_validator.api.metrics import BURN_GATE_FAIL_OPEN

        neuron = MagicMock()
        neuron.metagraph = self._make_metagraph(["1.2.3.4"])

        totals_before = sum(
            BURN_GATE_FAIL_OPEN.labels(reason=r)._value.get()
            for r in ("neuron_missing", "metagraph_missing", "metagraph_read_error")
        )
        assert is_allowed_peer_ip(neuron, "127.0.0.1")
        assert is_allowed_peer_ip(neuron, "1.2.3.4")
        assert not is_allowed_peer_ip(neuron, "9.9.9.9")
        totals_after = sum(
            BURN_GATE_FAIL_OPEN.labels(reason=r)._value.get()
            for r in ("neuron_missing", "metagraph_missing", "metagraph_read_error")
        )
        assert totals_after == totals_before
