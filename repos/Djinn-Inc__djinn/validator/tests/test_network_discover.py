"""Tests for /v1/network/validators and /v1/network/metagraph/miners endpoints.

These endpoints mirror the web `/api/validators/discover` and
`/api/miners/discover` routes so the static IPFS-deployable client can
fetch metagraph rows without a Vercel proxy. Response shape matches the
Next route output so the proxy can forward verbatim.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


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
    # Stakes are in TAO (float); the endpoint converts to rao on the wire.
    mg.total_stake = [nn["stake"] for nn in nodes]
    mg.alpha_stake = [nn.get("alpha_stake", nn["stake"]) for nn in nodes]
    mg.tao_stake = [nn.get("tao_stake", 0.0) for nn in nodes]
    mg.S = [nn["stake"] for nn in nodes]
    mg.I = [nn["incentive"] for nn in nodes]
    mg.E = [nn["emission"] for nn in nodes]
    mg.C = [nn.get("consensus", 0.0) for nn in nodes]
    mg.D = [nn.get("dividends", 0.0) for nn in nodes]
    mg.Tv = [nn["vtrust"] for nn in nodes]
    mg.hotkeys = [nn["hotkey"] for nn in nodes]
    # Ensure `hasattr(mg, "rank")` returns False so the endpoint defaults.
    del mg.rank
    del mg.trust
    return mg


def _mk_neuron(nodes: list[dict], own_uid: int = 0) -> MagicMock:
    neuron = MagicMock()
    neuron.metagraph = _mk_metagraph(nodes)
    neuron.uid = own_uid
    neuron._safe_item = staticmethod(int)
    neuron.get_validator_uids = lambda: [i for i, n in enumerate(nodes) if n["is_validator"]]
    return neuron


@pytest.fixture
def sample_nodes() -> list[dict]:
    """Two validators (uids 0, 1) and two miners (2, 3)."""
    return [
        {
            "ip": "45.79.88.1",
            "port": 8421,
            "hotkey": "5V0",
            "coldkey": "5C0",
            "is_validator": True,
            "stake": 10_000.5,
            "alpha_stake": 6_000.0,
            "tao_stake": 4_000.5,
            "incentive": 0.0,
            "emission": 0.0,
            "consensus": 0.91,
            "dividends": 0.5,
            "vtrust": 0.95,
        },
        {
            "ip": "45.79.88.2",
            "port": 8421,
            "hotkey": "5V1",
            "coldkey": "5C1",
            "is_validator": True,
            "stake": 5_000.0,
            "alpha_stake": 5_000.0,
            "tao_stake": 0.0,
            "incentive": 0.0,
            "emission": 0.0,
            "consensus": 0.88,
            "dividends": 0.3,
            "vtrust": 0.92,
        },
        {
            "ip": "167.150.153.11",
            "port": 8100,
            "hotkey": "5M2",
            "coldkey": "5CM2",
            "is_validator": False,
            "stake": 0.0,
            "alpha_stake": 0.0,
            "tao_stake": 0.0,
            "incentive": 0.4,
            "emission": 100.0,
            "consensus": 0.0,
            "dividends": 0.0,
            "vtrust": 0.0,
        },
        {
            "ip": "167.150.153.12",
            "port": 8100,
            "hotkey": "5M3",
            "coldkey": "5CM3",
            "is_validator": False,
            "stake": 0.0,
            "alpha_stake": 0.0,
            "tao_stake": 0.0,
            "incentive": 0.2,
            "emission": 50.0,
            "consensus": 0.0,
            "dividends": 0.0,
            "vtrust": 0.0,
        },
    ]


@pytest.fixture
def client(sample_nodes):
    neuron = _mk_neuron(sample_nodes, own_uid=0)
    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att, neuron=neuron)
        yield TestClient(app)
    finally:
        store.close()


def test_validators_returns_validator_subset(client):
    r = client.get("/v1/network/validators")
    assert r.status_code == 200
    body = r.json()
    assert body["validator_count"] == 2
    uids = [v["uid"] for v in body["validators"]]
    assert uids == [0, 1]  # sorted by stake desc


def test_validators_response_shape_matches_web(client):
    r = client.get("/v1/network/validators")
    body = r.json()
    v0 = body["validators"][0]
    required = {
        "uid", "ip", "port", "hotkey", "coldkey", "ss58Hotkey",
        "stake", "alphaStake", "taoStake", "incentive", "emission",
        "consensus", "trust", "validatorTrust", "dividends", "rank",
    }
    assert required.issubset(v0.keys())
    assert isinstance(v0["stake"], str)
    assert isinstance(v0["alphaStake"], str)
    assert isinstance(v0["taoStake"], str)
    assert isinstance(v0["emission"], str)
    assert isinstance(v0["consensus"], float)


def test_validators_stake_converted_to_rao(client):
    r = client.get("/v1/network/validators")
    body = r.json()
    v0 = body["validators"][0]
    # 10_000.5 TAO → 10_000_500_000_000 rao
    assert v0["stake"] == str(int(10_000.5 * 1e9))
    assert v0["alphaStake"] == str(int(6_000.0 * 1e9))
    assert v0["taoStake"] == str(int(4_000.5 * 1e9))


def test_validators_sorted_by_stake_desc(client):
    r = client.get("/v1/network/validators")
    body = r.json()
    stakes = [int(v["stake"]) for v in body["validators"]]
    assert stakes == sorted(stakes, reverse=True)


def test_validators_excludes_miners(client):
    r = client.get("/v1/network/validators")
    body = r.json()
    hotkeys = {v["hotkey"] for v in body["validators"]}
    assert "5M2" not in hotkeys
    assert "5M3" not in hotkeys


def test_validators_served_by_uid_is_own_uid(client):
    r = client.get("/v1/network/validators")
    body = r.json()
    assert body["served_by_uid"] == 0


def test_validators_ss58_mirrors_hotkey(client):
    r = client.get("/v1/network/validators")
    body = r.json()
    for v in body["validators"]:
        assert v["ss58Hotkey"] == v["hotkey"]


def test_miners_returns_miner_subset(client):
    r = client.get("/v1/network/metagraph/miners")
    assert r.status_code == 200
    body = r.json()
    assert body["miner_count"] == 2
    uids = [m["uid"] for m in body["miners"]]
    assert set(uids) == {2, 3}


def test_miners_response_shape_matches_web(client):
    r = client.get("/v1/network/metagraph/miners")
    body = r.json()
    m0 = body["miners"][0]
    required = {
        "uid", "ip", "port", "hotkey", "coldkey", "ss58Hotkey",
        "stake", "alphaStake", "taoStake", "incentive", "emission", "rank",
    }
    assert required.issubset(m0.keys())


def test_miners_sorted_by_incentive_desc(client):
    r = client.get("/v1/network/metagraph/miners")
    body = r.json()
    incentives = [m["incentive"] for m in body["miners"]]
    assert incentives == sorted(incentives, reverse=True)


def test_miners_excludes_validators(client):
    r = client.get("/v1/network/metagraph/miners")
    body = r.json()
    hotkeys = {m["hotkey"] for m in body["miners"]}
    assert "5V0" not in hotkeys
    assert "5V1" not in hotkeys


def test_miners_emission_converted_to_rao(client):
    r = client.get("/v1/network/metagraph/miners")
    body = r.json()
    # highest incentive (0.4) → uid 2, emission 100 TAO
    top = body["miners"][0]
    assert top["emission"] == str(int(100.0 * 1e9))


def test_validators_empty_when_no_metagraph():
    neuron = MagicMock()
    neuron.metagraph = None
    neuron.uid = None
    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att, neuron=neuron)
        client = TestClient(app)
        r = client.get("/v1/network/validators")
        assert r.status_code == 200
        body = r.json()
        assert body["validators"] == []
        assert body["validator_count"] == 0
    finally:
        store.close()


def test_miners_empty_when_no_metagraph():
    neuron = MagicMock()
    neuron.metagraph = None
    neuron.uid = None
    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att, neuron=neuron)
        client = TestClient(app)
        r = client.get("/v1/network/metagraph/miners")
        assert r.status_code == 200
        body = r.json()
        assert body["miners"] == []
        assert body["miner_count"] == 0
    finally:
        store.close()
