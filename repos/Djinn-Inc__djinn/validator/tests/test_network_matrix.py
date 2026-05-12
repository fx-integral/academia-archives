"""Tests for /v1/network/matrix endpoint.

The matrix endpoint fans out to every public peer validator's /health and
/v1/network/miners to build a validator×miner scoring matrix. This replaces
the centralized Vercel /api/network/matrix aggregator so static IPFS clients
can hit the wildcard router.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


def _make_stream_response(body_obj: dict | list, status_code: int = 200):
    """Shape a fake httpx streaming response for tests.

    _peer_get_bounded uses `.stream()` + `.aiter_bytes()` to cap body size
    under DoS. Tests synthesize a minimal streaming response: one chunk
    containing the JSON-encoded body, then StopAsyncIteration.
    """
    payload_bytes = json.dumps(body_obj).encode("utf-8")

    class _FakeResp:
        def __init__(self):
            self.status_code = status_code

        async def aiter_bytes(self):
            yield payload_bytes

    return _FakeResp()


@asynccontextmanager
async def _stream_cm(resp):
    yield resp


def _mk_axon(ip: str, port: int, hotkey: str) -> MagicMock:
    a = MagicMock()
    a.ip = ip
    a.port = port
    a.hotkey = hotkey
    return a


def _mk_metagraph(nodes: list[dict]) -> MagicMock:
    mg = MagicMock()
    n = len(nodes)
    mg.n = n
    mg.axons = [_mk_axon(nn["ip"], nn["port"], nn["hotkey"]) for nn in nodes]
    mg.coldkeys = [nn["coldkey"] for nn in nodes]
    mg.validator_permit = [nn["is_validator"] for nn in nodes]
    mg.S = [nn["stake"] for nn in nodes]
    mg.I = [nn["incentive"] for nn in nodes]
    mg.E = [nn["emission"] for nn in nodes]
    mg.validator_trust = [nn["vtrust"] for nn in nodes]
    mg.hotkeys = [nn["hotkey"] for nn in nodes]
    return mg


def _mk_neuron(nodes: list[dict], own_uid: int = 0) -> MagicMock:
    neuron = MagicMock()
    neuron.metagraph = _mk_metagraph(nodes)
    neuron.uid = own_uid
    neuron._safe_item = staticmethod(int)
    return neuron


@pytest.fixture
def sample_nodes() -> list[dict]:
    """Two public validators (uids 0, 1), one private-IP validator (2), and
    two miners (3, 4). Matrix only iterates public validators."""
    return [
        {
            "ip": "45.79.88.1",
            "port": 8421,
            "hotkey": "5V0",
            "coldkey": "5C0",
            "is_validator": True,
            "stake": 10_000.0,
            "incentive": 0.0,
            "emission": 0.0,
            "vtrust": 0.95,
        },
        {
            "ip": "45.79.88.2",
            "port": 8421,
            "hotkey": "5V1",
            "coldkey": "5C1",
            "is_validator": True,
            "stake": 5_000.0,
            "incentive": 0.0,
            "emission": 0.0,
            "vtrust": 0.92,
        },
        {
            "ip": "10.0.0.1",  # private, must be filtered
            "port": 8421,
            "hotkey": "5V2",
            "coldkey": "5C2",
            "is_validator": True,
            "stake": 1_000.0,
            "incentive": 0.0,
            "emission": 0.0,
            "vtrust": 0.88,
        },
        {
            "ip": "167.150.153.11",
            "port": 8100,
            "hotkey": "5M3",
            "coldkey": "5CM3",
            "is_validator": False,
            "stake": 0.0,
            "incentive": 0.4,
            "emission": 0.0,
            "vtrust": 0.0,
        },
        {
            "ip": "167.150.153.12",
            "port": 8100,
            "hotkey": "5M4",
            "coldkey": "5CM4",
            "is_validator": False,
            "stake": 0.0,
            "incentive": 0.2,
            "emission": 0.0,
            "vtrust": 0.0,
        },
    ]


def _make_client(nodes, monkeypatch, *, health_payload=None, miners_payload=None,
                 fail_health_for: set[str] | None = None,
                 fail_miners_for: set[str] | None = None,
                 spoof_uid_for: dict[str, int] | None = None,
                 spoof_hotkey_for: dict[str, str] | None = None):
    neuron = _mk_neuron(nodes, own_uid=0)

    fail_health = fail_health_for or set()
    fail_miners = fail_miners_for or set()
    spoof_uid = spoof_uid_for or {}
    spoof_hotkey = spoof_hotkey_for or {}

    # Per-IP uid/hotkey map so stub /health responses match the peer
    # identity the probe expects (v1351 identity check rejects mismatches).
    ip_to_uid = {n["ip"]: i for i, n in enumerate(nodes)}
    ip_to_hotkey = {n["ip"]: n["hotkey"] for n in nodes}
    # Self-probe rewrites the IP to 127.0.0.1 (loopback) to dodge NAT
    # hairpin flakiness on the validator's own external IP. Mirror any
    # per-IP overrides from the own_uid IP so tests targeting that
    # validator (e.g. spoof_hotkey_for) still hit the loopback path.
    own_ip = nodes[0]["ip"]
    ip_to_uid["127.0.0.1"] = 0
    ip_to_hotkey["127.0.0.1"] = nodes[0]["hotkey"]
    if own_ip in spoof_uid:
        spoof_uid["127.0.0.1"] = spoof_uid[own_ip]
    if own_ip in spoof_hotkey:
        spoof_hotkey["127.0.0.1"] = spoof_hotkey[own_ip]
    if own_ip in fail_health:
        fail_health = set(fail_health) | {"127.0.0.1"}
    if own_ip in fail_miners:
        fail_miners = set(fail_miners) | {"127.0.0.1"}

    default_miners = miners_payload or {
        "miners": [
            {"uid": 3, "hotkey": "5M3", "weight": 0.7, "accuracy": 0.9, "uptime": 0.95},
            {"uid": 4, "hotkey": "5M4", "weight": 0.3, "accuracy": 0.8, "uptime": 0.88},
        ]
    }

    def _build_response(url):
        """Return (status_code, body) for a mocked peer URL."""
        if "/health" in url:
            if any(ip in url for ip in fail_health):
                return 500, {}
            matched_uid = 99
            matched_hotkey = ""
            for ip, uid in ip_to_uid.items():
                if ip in url:
                    matched_uid = spoof_uid.get(ip, uid)
                    matched_hotkey = spoof_hotkey.get(ip, ip_to_hotkey[ip])
                    break
            payload = dict(health_payload) if health_payload else {}
            payload.setdefault("status", "ok")
            payload.setdefault("version", "1349")
            payload["uid"] = matched_uid
            payload["hotkey"] = matched_hotkey
            return 200, payload
        if "/v1/network/miners" in url:
            if any(ip in url for ip in fail_miners):
                return 500, {}
            return 200, default_miners
        return 404, {}

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, *args, **kwargs):
            status, body = _build_response(url)
            resp = MagicMock()
            resp.status_code = status
            resp.json = lambda: body
            return resp

        def stream(self, method, url, *args, **kwargs):
            status, body = _build_response(url)
            return _stream_cm(_make_stream_response(body, status_code=status))

        async def aclose(self):
            return None

    monkeypatch.setattr("djinn_validator.api.server.httpx.AsyncClient", _StubClient)

    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att, neuron=neuron)
        return TestClient(app), store
    except Exception:
        store.close()
        raise


@pytest.fixture
def client(sample_nodes, monkeypatch):
    c, store = _make_client(sample_nodes, monkeypatch)
    try:
        yield c
    finally:
        store.close()


def test_matrix_returns_public_validators_only(client):
    r = client.get("/v1/network/matrix")
    assert r.status_code == 200
    body = r.json()
    uids = [v["uid"] for v in body["validators"]]
    assert uids == [0, 1]  # uid 2 filtered (private IP)


def test_matrix_response_shape(client):
    r = client.get("/v1/network/matrix")
    body = r.json()
    assert "validators" in body
    assert "minerUids" in body
    assert "timestamp" in body
    assert "served_by_uid" in body
    v0 = body["validators"][0]
    for key in ("uid", "ip", "port", "stake", "version", "healthy", "miners"):
        assert key in v0


def test_matrix_joins_miners_by_uid(client):
    r = client.get("/v1/network/matrix")
    body = r.json()
    # Both stubbed validators return the same miner set; uids 3 and 4
    assert body["minerUids"] == [3, 4]
    for v in body["validators"]:
        assert set(v["miners"].keys()) == {"3", "4"} or set(v["miners"].keys()) == {3, 4}


def test_matrix_healthy_reflects_status_ok(client):
    r = client.get("/v1/network/matrix")
    body = r.json()
    for v in body["validators"]:
        assert v["healthy"] is True
        assert v["version"] == "1349"


def test_matrix_served_by_uid_is_own_uid(client):
    r = client.get("/v1/network/matrix")
    body = r.json()
    assert body["served_by_uid"] == 0


def test_matrix_stake_is_rao_string(client):
    r = client.get("/v1/network/matrix")
    body = r.json()
    v0 = next(v for v in body["validators"] if v["uid"] == 0)
    # 10_000.0 TAO → 10_000_000_000_000 rao
    assert v0["stake"] == str(int(10_000.0 * 1e9))


def test_matrix_unhealthy_peer_still_listed(sample_nodes, monkeypatch):
    c, store = _make_client(
        sample_nodes, monkeypatch,
        fail_health_for={"45.79.88.2"},
    )
    try:
        r = c.get("/v1/network/matrix")
        body = r.json()
        v1 = next(v for v in body["validators"] if v["uid"] == 1)
        assert v1["healthy"] is False
        assert v1["version"] is None
    finally:
        store.close()


def test_matrix_miners_fetch_failure_leaves_empty_map(sample_nodes, monkeypatch):
    c, store = _make_client(
        sample_nodes, monkeypatch,
        fail_miners_for={"45.79.88.2"},
    )
    try:
        r = c.get("/v1/network/matrix")
        body = r.json()
        v1 = next(v for v in body["validators"] if v["uid"] == 1)
        assert v1["miners"] == {}
        # /health succeeded, so the validator is healthy regardless of
        # whether the secondary miners endpoint responded.
        assert v1["healthy"] is True
        assert v1["version"] == "1349"
        # Other validator still populated
        v0 = next(v for v in body["validators"] if v["uid"] == 0)
        assert len(v0["miners"]) == 2
    finally:
        store.close()




def test_matrix_caches_within_ttl(client):
    r1 = client.get("/v1/network/matrix")
    r2 = client.get("/v1/network/matrix")
    assert r1.json()["timestamp"] == r2.json()["timestamp"]


def test_matrix_empty_when_no_neuron():
    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att, neuron=None)
        c = TestClient(app)
        r = c.get("/v1/network/matrix")
        assert r.status_code == 200
        body = r.json()
        assert body["validators"] == []
        assert body["minerUids"] == []
    finally:
        store.close()


def test_matrix_rejects_peer_with_spoofed_uid(sample_nodes, monkeypatch):
    """A peer on IP 45.79.88.2 (metagraph uid=1) claiming uid=42 in /health
    is port-squatting or impersonating. Reject it: mark unhealthy, miners empty."""
    c, store = _make_client(
        sample_nodes, monkeypatch,
        spoof_uid_for={"45.79.88.2": 42},
    )
    try:
        r = c.get("/v1/network/matrix")
        body = r.json()
        v1 = next(v for v in body["validators"] if v["uid"] == 1)
        assert v1["healthy"] is False
        assert v1["version"] is None
        # uid=0 still healthy (stub matches for that IP)
        v0 = next(v for v in body["validators"] if v["uid"] == 0)
        assert v0["healthy"] is True
    finally:
        store.close()


def test_matrix_rejects_peer_with_spoofed_hotkey(sample_nodes, monkeypatch):
    """A peer whose /health hotkey doesn't match the metagraph hotkey is
    rejected — defense against a validator pretending to be a different UID's
    service on 8421."""
    c, store = _make_client(
        sample_nodes, monkeypatch,
        spoof_hotkey_for={"45.79.88.2": "5IMPOSTOR"},
    )
    try:
        r = c.get("/v1/network/matrix")
        body = r.json()
        v1 = next(v for v in body["validators"] if v["uid"] == 1)
        assert v1["healthy"] is False
        assert v1["version"] is None
    finally:
        store.close()


def test_matrix_rejects_oversized_peer_body(sample_nodes, monkeypatch):
    """A malicious peer streaming >4MB as /health must be dropped.
    Simulates by making the stub stream a chunk that exceeds the cap."""
    neuron = _mk_neuron(sample_nodes, own_uid=0)

    class _HugeResp:
        status_code = 200

        async def aiter_bytes(self):
            # Exceeds the 4MB cap; _peer_get_bounded must abort.
            import os
            yield os.urandom(5 * 1024 * 1024)

    class _GiantStubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json = lambda: {}
            return resp

        def stream(self, method, url, *args, **kwargs):
            return _stream_cm(_HugeResp())

        async def aclose(self):
            return None

    monkeypatch.setattr("djinn_validator.api.server.httpx.AsyncClient", _GiantStubClient)
    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att, neuron=neuron)
        c = TestClient(app)
        r = c.get("/v1/network/matrix")
        body = r.json()
        for v in body["validators"]:
            assert v["healthy"] is False
            assert v["version"] is None
    finally:
        store.close()


def test_matrix_accepts_peer_without_hotkey_field(sample_nodes, monkeypatch):
    """Backwards-compat: a peer on older firmware that doesn't return 'hotkey'
    in /health is still accepted as long as uid matches."""
    c, store = _make_client(
        sample_nodes, monkeypatch,
        spoof_hotkey_for={n["ip"]: "" for n in sample_nodes},
    )
    try:
        r = c.get("/v1/network/matrix")
        body = r.json()
        # All public validators (uids 0 and 1) healthy; hotkey was empty
        for v in body["validators"]:
            assert v["healthy"] is True
    finally:
        store.close()


def test_matrix_rejects_empty_hotkey_when_strict_mode_enabled(sample_nodes, monkeypatch):
    """DJINN_FF_STRICT_PEER_HOTKEY=True must reject any peer that returns
    an empty hotkey. Closes the empty-hotkey bypass flagged by fresh-eyes
    audit on v1352 — once the whole fleet is on v1351+, operators flip
    this flag and the backwards-compat escape hatch closes."""
    import djinn_validator.feature_flags as _ff_mod

    strict_flags = _ff_mod.FeatureFlags(strict_peer_hotkey=True)
    monkeypatch.setattr(_ff_mod, "flags", strict_flags)
    c, store = _make_client(
        sample_nodes, monkeypatch,
        spoof_hotkey_for={n["ip"]: "" for n in sample_nodes},
    )
    try:
        r = c.get("/v1/network/matrix")
        body = r.json()
        # Strict mode: no empty hotkey → no healthy entries
        for v in body["validators"]:
            assert v["healthy"] is False
            assert v["version"] is None
    finally:
        store.close()


def test_matrix_accepts_matching_hotkey_when_strict_mode_enabled(sample_nodes, monkeypatch):
    """Strict mode still accepts a peer whose hotkey matches the metagraph."""
    import djinn_validator.feature_flags as _ff_mod

    strict_flags = _ff_mod.FeatureFlags(strict_peer_hotkey=True)
    monkeypatch.setattr(_ff_mod, "flags", strict_flags)
    c, store = _make_client(sample_nodes, monkeypatch)
    try:
        r = c.get("/v1/network/matrix")
        body = r.json()
        healthy = [v for v in body["validators"] if v["healthy"]]
        assert len(healthy) >= 1
    finally:
        store.close()


def test_matrix_empty_when_no_metagraph():
    neuron = MagicMock()
    neuron.metagraph = None
    neuron.uid = 0
    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att, neuron=neuron)
        c = TestClient(app)
        r = c.get("/v1/network/matrix")
        assert r.status_code == 200
        body = r.json()
        assert body["validators"] == []
    finally:
        store.close()
