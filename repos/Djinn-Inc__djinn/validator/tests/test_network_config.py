"""Tests for /v1/network/config (Sprint B Stage 4).

Mirrors the legacy /api/network/config Vercel route so static IPFS clients
and the SDK can discover the network via a single validator hop without
going through a Vercel proxy.
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
    mg.n = len(nodes)
    mg.axons = [_mk_axon(n["ip"], n["port"], n["hotkey"]) for n in nodes]
    mg.coldkeys = [n["coldkey"] for n in nodes]
    mg.validator_permit = [n["is_validator"] for n in nodes]
    mg.total_stake = [n["stake"] for n in nodes]
    mg.alpha_stake = [n["stake"] for n in nodes]
    mg.tao_stake = [0.0 for _ in nodes]
    mg.S = [n["stake"] for n in nodes]
    mg.I = [0.0 for _ in nodes]
    mg.E = [0.0 for _ in nodes]
    mg.C = [0.0 for _ in nodes]
    mg.D = [0.0 for _ in nodes]
    mg.Tv = [0.0 for _ in nodes]
    mg.hotkeys = [n["hotkey"] for n in nodes]
    del mg.rank
    del mg.trust
    return mg


def _mk_neuron(nodes: list[dict], own_uid: int = 0) -> MagicMock:
    neuron = MagicMock()
    neuron.metagraph = _mk_metagraph(nodes)
    neuron.uid = own_uid
    neuron.get_validator_uids = lambda: [
        i for i, n in enumerate(nodes) if n["is_validator"]
    ]
    return neuron


@pytest.fixture
def sample_nodes() -> list[dict]:
    """Three validators (one with port=0 — should be filtered) + one miner."""
    return [
        {
            "ip": "45.79.88.1",
            "port": 8421,
            "hotkey": "5V0",
            "coldkey": "5C0",
            "is_validator": True,
            "stake": 10_000.0,
        },
        {
            "ip": "45.79.88.2",
            "port": 8421,
            "hotkey": "5V1",
            "coldkey": "5C1",
            "is_validator": True,
            "stake": 5_000.0,
        },
        {
            "ip": "45.79.88.3",
            "port": 0,  # validator permit but axon not published — should be skipped
            "hotkey": "5V2",
            "coldkey": "5C2",
            "is_validator": True,
            "stake": 1_000.0,
        },
        {
            "ip": "167.150.153.11",
            "port": 8100,
            "hotkey": "5M3",
            "coldkey": "5CM3",
            "is_validator": False,  # miner — excluded from validators list
            "stake": 0.0,
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


class TestNetworkConfigBasics:
    def test_returns_200(self, client):
        r = client.get("/v1/network/config")
        assert r.status_code == 200

    def test_response_top_level_keys(self, client):
        body = client.get("/v1/network/config").json()
        required = {"validators", "chain_id", "contracts", "shamir", "cached_at"}
        assert required.issubset(body.keys())


class TestNetworkConfigValidators:
    def test_only_validators_with_axon_ip_port_returned(self, client):
        body = client.get("/v1/network/config").json()
        uids = [v["uid"] for v in body["validators"]]
        # UID 0 and 1 pass; UID 2 has port=0; UID 3 is a miner.
        assert uids == [0, 1]

    def test_validator_shape_matches_web_contract(self, client):
        v = client.get("/v1/network/config").json()["validators"][0]
        required = {"uid", "name", "endpoint", "pubkey"}
        assert required.issubset(v.keys())
        assert v["endpoint"].startswith("http://")
        # pubkey is null until IdentityResponse publishes one — preserve
        # legacy Vercel behavior so SDK consumers see no surprise diff.
        assert v["pubkey"] is None

    def test_name_is_uid_stamp(self, client):
        body = client.get("/v1/network/config").json()
        for v in body["validators"]:
            assert v["name"] == f"UID {v['uid']}"

    def test_endpoint_is_ip_and_port(self, client):
        body = client.get("/v1/network/config").json()
        # UID 0 → 45.79.88.1:8421
        v0 = next(v for v in body["validators"] if v["uid"] == 0)
        assert v0["endpoint"] == "http://45.79.88.1:8421"


class TestNetworkConfigContracts:
    def test_contract_keys_present(self, client):
        contracts = client.get("/v1/network/config").json()["contracts"]
        required = {
            "signal_commitment",
            "escrow",
            "collateral",
            "account",
            "audit",
            "credit_ledger",
            "key_recovery",
            "usdc",
        }
        assert required.issubset(contracts.keys())

    def test_contracts_are_checksum_addresses(self, client):
        contracts = client.get("/v1/network/config").json()["contracts"]
        for key, addr in contracts.items():
            assert isinstance(addr, str), f"{key}: expected str, got {type(addr)}"
            assert addr.startswith("0x"), f"{key}: missing 0x prefix: {addr}"
            assert len(addr) == 42, f"{key}: wrong length: {addr}"

    def test_signal_commitment_matches_canonical_sepolia(self, client):
        contracts = client.get("/v1/network/config").json()["contracts"]
        assert (
            contracts["signal_commitment"]
            == "0x4712479Ba57c9ED40405607b2B18967B359209C0"
        )


class TestNetworkConfigShamir:
    def test_shamir_keys_present(self, client):
        shamir = client.get("/v1/network/config").json()["shamir"]
        assert "n" in shamir
        assert "k" in shamir
        assert isinstance(shamir["n"], int)
        assert isinstance(shamir["k"], int)

    def test_shamir_k_le_n(self, client):
        shamir = client.get("/v1/network/config").json()["shamir"]
        assert shamir["k"] <= shamir["n"]


class TestNetworkConfigChainId:
    def test_chain_id_integer(self, client):
        cid = client.get("/v1/network/config").json()["chain_id"]
        assert isinstance(cid, int)
        assert cid > 0


class TestNetworkConfigNoMetagraph:
    def test_no_neuron_returns_empty_validator_list(self):
        """Validators list degrades to [] when metagraph is unavailable,
        but the rest of the config (contracts, chain_id, shamir) still
        serializes — a static client can at least bootstrap with addresses."""
        store = ShareStore()
        try:
            orch = PurchaseOrchestrator(store)
            att = OutcomeAttestor()
            app = create_app(store, orch, att, neuron=None)
            c = TestClient(app)
            body = c.get("/v1/network/config").json()
            assert body["validators"] == []
            assert "escrow" in body["contracts"]
            assert body["chain_id"] > 0
        finally:
            store.close()
