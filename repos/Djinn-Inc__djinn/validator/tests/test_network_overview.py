"""Tests for /v1/network/overview aggregator endpoint.

This endpoint replaces the centralized Vercel /api/network/status so static
IPFS clients can render the /network dashboard without a middleman. It
aggregates validators, miners, per-validator health, and cluster stats in
one JSON response keyed on the serving validator's own metagraph view.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


def _make_stream_response(body_obj: dict | list, status_code: int = 200):
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
    """Build a minimal metagraph mock. Each node is {ip, port, hotkey,
    coldkey, is_validator, stake, incentive, emission, vtrust}."""
    mg = MagicMock()
    n = len(nodes)
    mg.n = n
    mg.axons = [_mk_axon(n["ip"], n["port"], n["hotkey"]) for n in nodes]
    mg.coldkeys = [n["coldkey"] for n in nodes]
    mg.validator_permit = [n["is_validator"] for n in nodes]
    mg.S = [n["stake"] for n in nodes]
    mg.I = [n["incentive"] for n in nodes]
    mg.E = [n["emission"] for n in nodes]
    mg.validator_trust = [n["vtrust"] for n in nodes]
    mg.hotkeys = [n["hotkey"] for n in nodes]
    return mg


def _mk_neuron(nodes: list[dict], own_uid: int = 0) -> MagicMock:
    neuron = MagicMock()
    neuron.metagraph = _mk_metagraph(nodes)
    neuron.uid = own_uid
    neuron._safe_item = staticmethod(int)
    neuron.get_validator_uids = lambda: [i for i, n in enumerate(nodes) if n["is_validator"]]

    def _get_axon_info(uid: int) -> dict:
        n = nodes[uid]
        return {"ip": n["ip"], "port": n["port"], "hotkey": n["hotkey"], "coldkey": n["coldkey"]}

    neuron.get_axon_info = _get_axon_info
    return neuron


@pytest.fixture
def sample_nodes() -> list[dict]:
    """Three validators (uids 0, 1, 2) and two miners (3, 4), plus a
    bad-IP validator (5) that should be filtered.

    IPs must pass `ipaddress.ip_address(x).is_global`, which rejects RFC
    5737 TEST-NET docs ranges (198.51.100.x, 203.0.113.x). Using public
    ranges (45.x) keeps the fixture honest for SSRF-filter testing."""
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
            "stake": 8_000.0,
            "incentive": 0.0,
            "emission": 0.0,
            "vtrust": 0.92,
        },
        {
            "ip": "45.79.88.3",
            "port": 8421,
            "hotkey": "5V2",
            "coldkey": "5C2",
            "is_validator": True,
            "stake": 5_000.0,
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
            "emission": 0.1,
            "vtrust": 0.0,
        },
        {
            "ip": "167.150.153.12",
            "port": 8100,
            "hotkey": "5M4",
            "coldkey": "5CM3",
            "is_validator": False,
            "stake": 0.0,
            "incentive": 0.2,
            "emission": 0.05,
            "vtrust": 0.0,
        },
        {
            "ip": "10.0.0.1",
            "port": 8421,
            "hotkey": "5V5",
            "coldkey": "5C5",
            "is_validator": True,
            "stake": 100.0,
            "incentive": 0.0,
            "emission": 0.0,
            "vtrust": 0.0,
        },
    ]


@pytest.fixture
def client(sample_nodes, monkeypatch):
    """Build the FastAPI app with a fake neuron + stubbed peer health probes."""
    neuron = _mk_neuron(sample_nodes, own_uid=0)

    # Build URL → (uid, hotkey) map so stub health responses match the
    # peer identity the probe expects. Identity check (v1351) rejects
    # peers whose /health uid/hotkey doesn't match the metagraph record.
    ip_to_uid = {n["ip"]: i for i, n in enumerate(sample_nodes)}
    ip_to_hotkey = {n["ip"]: n["hotkey"] for n in sample_nodes}
    # Self-probe rewrites the IP to 127.0.0.1 (loopback) to dodge NAT
    # hairpin flakiness on the validator's own external IP. The stub
    # has to recognize that URL as the serving validator (own_uid=0
    # in this fixture).
    ip_to_uid["127.0.0.1"] = 0
    ip_to_hotkey["127.0.0.1"] = sample_nodes[0]["hotkey"]

    async def _fake_peer_probe(url):
        resp = MagicMock()
        resp.status_code = 200
        matched_uid = 99
        matched_hotkey = ""
        for ip, uid in ip_to_uid.items():
            if ip in url:
                matched_uid = uid
                matched_hotkey = ip_to_hotkey[ip]
                break
        resp.json = lambda: {
            "status": "ok",
            "version": "1200",
            "uid": matched_uid,
            "hotkey": matched_hotkey,
            "shares_held": 42,
            "chain_connected": True,
            "bt_connected": True,
            "settlement_registered": True,
            "settlement_contract": "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E",
        }
        return resp

    def _build_body(url):
        body = {
            "status": "ok",
            "version": "1200",
            "uid": 99,
            "hotkey": "",
            "shares_held": 42,
            "chain_connected": True,
            "bt_connected": True,
            "settlement_registered": True,
            "settlement_contract": "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E",
        }
        for ip, uid in ip_to_uid.items():
            if ip in url:
                body["uid"] = uid
                body["hotkey"] = ip_to_hotkey[ip]
                break
        return body

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, *args, **kwargs):
            return await _fake_peer_probe(url)

        def stream(self, method, url, *args, **kwargs):
            return _stream_cm(_make_stream_response(_build_body(url), status_code=200))

        async def aclose(self):
            return None

    monkeypatch.setattr("djinn_validator.api.server.httpx.AsyncClient", _StubClient)

    store = ShareStore()
    purchase = PurchaseOrchestrator(store)
    outcomes = OutcomeAttestor()
    app = create_app(
        store,
        purchase,
        outcomes,
        neuron=neuron,
    )
    return TestClient(app)


def test_overview_returns_summary(client):
    resp = client.get("/v1/network/overview")
    assert resp.status_code == 200
    body = resp.json()

    assert body["summary"] is not None
    s = body["summary"]
    # Only 3 public validators survive the IP filter (uid 5 has 10.0.0.1)
    assert s["totalValidators"] == 3
    # All 2 miners visible; 10/192/127 filter only applies to validators
    assert s["totalMiners"] == 2
    # All three validators stubbed to report status=ok version=1200
    assert s["validatorsHealthy"] == 3
    assert s["highestVersion"] == 1200


def test_overview_lists_validators_sorted_by_stake(client):
    resp = client.get("/v1/network/overview")
    body = resp.json()
    uids = [v["uid"] for v in body["validators"]]
    assert uids == [0, 1, 2]  # stake descending
    # Each validator carries an ss58Hotkey, incentive, emission, validatorTrust
    for v in body["validators"]:
        assert "ss58Hotkey" in v
        assert "validatorTrust" in v
        assert "health" in v


def test_overview_lists_miners_with_scoring(client):
    resp = client.get("/v1/network/overview")
    body = resp.json()
    miners = body["miners"]
    assert len(miners) == 2
    # Sorted by incentive descending
    assert miners[0]["incentive"] >= miners[1]["incentive"]
    # IP preserved
    assert miners[0]["ip"] in {"167.150.153.11", "167.150.153.12"}


def test_overview_filters_private_ips_on_validators(client, sample_nodes):
    resp = client.get("/v1/network/overview")
    body = resp.json()
    val_uids = [v["uid"] for v in body["validators"]]
    # uid 5 has 10.0.0.1 — must not appear in the validator list
    assert 5 not in val_uids


def test_overview_computes_ip_clusters(client):
    resp = client.get("/v1/network/overview")
    body = resp.json()
    # 167.150.153.11 and 167.150.153.12 share /24 prefix 167.150.153
    assert "167.150.153" in body["ipClusters"]
    assert sorted(body["ipClusters"]["167.150.153"]) == [3, 4]


def test_overview_no_neuron_returns_empty(monkeypatch):
    store = ShareStore()
    purchase = PurchaseOrchestrator(store)
    outcomes = OutcomeAttestor()
    app = create_app(store, purchase, outcomes, neuron=None)
    c = TestClient(app)
    resp = c.get("/v1/network/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] is None
    assert body["validators"] == []
    assert body["miners"] == []


def test_overview_caches_within_ttl(client):
    r1 = client.get("/v1/network/overview")
    r2 = client.get("/v1/network/overview")
    # The cache should make ts2 identical to ts1 (same served_at_ms).
    assert r1.json()["served_at_ms"] == r2.json()["served_at_ms"]


def test_overview_self_probe_uses_loopback(sample_nodes, monkeypatch):
    """Self-probe must hit 127.0.0.1, not the validator's external IP.

    Probing our own external IP from inside the container hits NAT-hairpin
    paths that intermittently exceed the 5s probe budget, leaving the
    bootstrap validator reporting itself as 'unreachable' on its own
    /v1/network/overview (and therefore on djinn.gg/network).
    """
    neuron = _mk_neuron(sample_nodes, own_uid=0)
    own_ip = sample_nodes[0]["ip"]  # 45.79.88.1 in fixture
    own_hotkey = sample_nodes[0]["hotkey"]
    seen_urls: list[str] = []

    ip_to_uid = {n["ip"]: i for i, n in enumerate(sample_nodes)}
    ip_to_hotkey = {n["ip"]: n["hotkey"] for n in sample_nodes}
    ip_to_uid["127.0.0.1"] = 0
    ip_to_hotkey["127.0.0.1"] = own_hotkey

    def _build_body(url):
        body = {
            "status": "ok",
            "version": "1200",
            "uid": 99,
            "hotkey": "",
            "shares_held": 42,
            "chain_connected": True,
            "bt_connected": True,
            "settlement_registered": True,
        }
        for ip, uid in ip_to_uid.items():
            if ip in url:
                body["uid"] = uid
                body["hotkey"] = ip_to_hotkey[ip]
                break
        return body

    class _StubClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def aclose(self): return None

        def stream(self, method, url, *a, **k):
            seen_urls.append(url)
            return _stream_cm(_make_stream_response(_build_body(url), 200))

    monkeypatch.setattr("djinn_validator.api.server.httpx.AsyncClient", _StubClient)

    store = ShareStore()
    purchase = PurchaseOrchestrator(store)
    outcomes = OutcomeAttestor()
    app = create_app(store, purchase, outcomes, neuron=neuron)
    c = TestClient(app)

    resp = c.get("/v1/network/overview")
    assert resp.status_code == 200

    # Self-probe must NOT call the external IP, MUST call 127.0.0.1.
    self_external = [u for u in seen_urls if own_ip in u]
    self_loopback = [u for u in seen_urls if "127.0.0.1" in u]
    assert self_external == [], f"unexpected external self-probe: {self_external}"
    assert self_loopback, f"missing loopback self-probe in {seen_urls}"


# ---------------------------------------------------------------------------
# /v1/network/validator/{uid} — per-validator detail endpoint
# ---------------------------------------------------------------------------


def test_validator_detail_self_served(client):
    """Fast path: neuron.uid == requested uid, serves from local state."""
    resp = client.get("/v1/network/validator/0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["uid"] == 0
    # Self-served health status is always "ok" with local version.
    assert body["health"]["status"] == "ok"
    assert body["health"]["uid"] == 0
    # Metagraph view present with the axon data.
    assert body["metagraph"]["ip"] == "45.79.88.1"
    assert body["metagraph"]["port"] == 8421


def test_validator_detail_peer_path(client):
    """Peer path: uid != neuron.uid, probes via httpx stub."""
    resp = client.get("/v1/network/validator/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["uid"] == 1
    # Health comes from the stub (version "1200", uid 99 from stub payload)
    assert body["health"] is not None
    assert body["health"]["version"] == "1200"
    assert body["metagraph"]["ip"] == "45.79.88.2"


def test_validator_detail_uid_out_of_range(client):
    resp = client.get("/v1/network/validator/9999")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert "out of range" in body["error"].lower()


def test_validator_detail_invalid_uid_negative(client):
    # FastAPI will reject negative ints at the path level (422), but our
    # handler also guards. Accept either the validation error or our own.
    resp = client.get("/v1/network/validator/-1")
    assert resp.status_code in {200, 422}


def test_validator_detail_not_a_validator(client):
    # uid 3 is a miner in the sample fixture.
    resp = client.get("/v1/network/validator/3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert "not a validator" in body["error"].lower()


def test_validator_detail_private_ip_rejected(client):
    # uid 5 has ip 10.0.0.1 — fails the public-IP filter.
    resp = client.get("/v1/network/validator/5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert "reachable" in body["error"].lower()


def test_validator_detail_caches_within_ttl(client):
    # Second call within 60s TTL returns the exact same dict (identity check
    # not guaranteed across JSON roundtrip, so verify shape + timestamps
    # match via field comparison on health/uid).
    r1 = client.get("/v1/network/validator/1")
    r2 = client.get("/v1/network/validator/1")
    assert r1.json() == r2.json()


def test_validator_detail_no_neuron_returns_not_found():
    store = ShareStore()
    purchase = PurchaseOrchestrator(store)
    outcomes = OutcomeAttestor()
    app = create_app(store, purchase, outcomes, neuron=None)
    c = TestClient(app)
    resp = c.get("/v1/network/validator/0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert "neuron" in body["error"].lower()
