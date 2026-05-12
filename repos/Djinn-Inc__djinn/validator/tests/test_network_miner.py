"""Tests for /v1/network/miner/{uid} fan-out aggregator (Sprint B Stage 6).

Mirrors the legacy /api/network/miner/[uid] Vercel route: fan out to every
public validator's /v1/miner/{uid}/scores, include the requested miner's
metagraph entry. Static IPFS clients hit this through the wildcard router
so they don't need a centralized proxy.
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


def _make_stream_response(body_obj, status_code: int = 200):
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
    mg.n = len(nodes)
    mg.axons = [_mk_axon(n["ip"], n["port"], n["hotkey"]) for n in nodes]
    mg.validator_permit = [n["is_validator"] for n in nodes]
    mg.S = [n["stake"] for n in nodes]
    mg.I = [n["incentive"] for n in nodes]
    mg.E = [n["emission"] for n in nodes]
    mg.hotkeys = [n["hotkey"] for n in nodes]
    return mg


def _mk_neuron(nodes: list[dict], own_uid: int = 0) -> MagicMock:
    neuron = MagicMock()
    neuron.metagraph = _mk_metagraph(nodes)
    neuron.uid = own_uid
    neuron._safe_item = staticmethod(int)
    return neuron


@pytest.fixture
def sample_nodes() -> list[dict]:
    """Two public validators (0,1), one private-IP validator (2), three miners (3,4,5)."""
    return [
        {"ip": "45.79.88.1", "port": 8421, "hotkey": "5V0",
         "is_validator": True, "stake": 10_000.0, "incentive": 0.0, "emission": 0.0},
        {"ip": "45.79.88.2", "port": 8421, "hotkey": "5V1",
         "is_validator": True, "stake": 5_000.0, "incentive": 0.0, "emission": 0.0},
        {"ip": "10.0.0.1", "port": 8421, "hotkey": "5V2",
         "is_validator": True, "stake": 1_000.0, "incentive": 0.0, "emission": 0.0},
        {"ip": "167.150.153.11", "port": 8100, "hotkey": "5M3",
         "is_validator": False, "stake": 0.0, "incentive": 0.4, "emission": 1.5},
        {"ip": "167.150.153.12", "port": 8100, "hotkey": "5M4",
         "is_validator": False, "stake": 0.0, "incentive": 0.2, "emission": 0.75},
        {"ip": "167.150.153.13", "port": 8100, "hotkey": "5M5",
         "is_validator": False, "stake": 0.0, "incentive": 0.1, "emission": 0.25},
    ]


def _make_client(
    nodes,
    monkeypatch,
    *,
    scores_payload: dict | None = None,
    fail_scores_for: set[str] | None = None,
    probe_log: list[str] | None = None,
):
    neuron = _mk_neuron(nodes, own_uid=99)
    fail_scores = fail_scores_for or set()
    default_scores = scores_payload or {
        "uid": 3,
        "found": True,
        "hotkey": "5M3",
        "accuracy": 0.9,
        "uptime": 0.95,
        "queries_total": 100,
        "queries_correct": 90,
    }

    def _build_response(url: str):
        if probe_log is not None:
            probe_log.append(url)
        if "/v1/miner/" in url and "/scores" in url:
            if any(ip in url for ip in fail_scores):
                return 500, {}
            return 200, default_scores
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
    orch = PurchaseOrchestrator(store)
    att = OutcomeAttestor()
    app = create_app(store, orch, att, neuron=neuron)
    return TestClient(app), store


@pytest.fixture
def client(sample_nodes, monkeypatch):
    c, store = _make_client(sample_nodes, monkeypatch)
    try:
        yield c
    finally:
        store.close()


class TestNetworkMinerBasics:
    def test_invalid_uid_400(self, client):
        for bad in (-1, 65536, 99999):
            r = client.get(f"/v1/network/miner/{bad}")
            assert r.status_code == 400

    def test_no_metagraph_returns_empty(self, monkeypatch, sample_nodes):
        # Build a client with no neuron; endpoint must degrade to empty.
        store = ShareStore()
        try:
            orch = PurchaseOrchestrator(store)
            att = OutcomeAttestor()
            app = create_app(store, orch, att, neuron=None)
            c = TestClient(app)
            r = c.get("/v1/network/miner/3")
            assert r.status_code == 200
            assert r.json() == {"uid": 3, "scores": [], "metagraph": None}
        finally:
            store.close()

    def test_response_shape(self, client):
        body = client.get("/v1/network/miner/3").json()
        assert set(body.keys()) == {"uid", "scores", "metagraph"}
        assert body["uid"] == 3
        assert isinstance(body["scores"], list)


class TestNetworkMinerMetagraph:
    def test_metagraph_view_populated_for_known_uid(self, client):
        body = client.get("/v1/network/miner/3").json()
        mg = body["metagraph"]
        assert mg is not None
        assert mg["ip"] == "167.150.153.11"
        assert mg["isValidator"] is False
        assert mg["incentive"] == 0.4
        # Stake / emission converted to rao strings (x1e9).
        assert mg["emission"] == str(int(1.5 * 1e9))

    def test_metagraph_null_for_out_of_range_uid(self, client):
        body = client.get("/v1/network/miner/500").json()
        # Out-of-range UID: no local metagraph entry, but peers may still
        # respond (they have their own metagraph view) — same as Vercel.
        assert body["metagraph"] is None
        assert body["uid"] == 500

    def test_metagraph_marks_validator_uid_as_validator(self, client):
        body = client.get("/v1/network/miner/0").json()
        assert body["metagraph"]["isValidator"] is True


class TestNetworkMinerFanout:
    def test_only_public_validators_probed(self, sample_nodes, monkeypatch):
        probe_log: list[str] = []
        c, store = _make_client(sample_nodes, monkeypatch, probe_log=probe_log)
        try:
            c.get("/v1/network/miner/3")
            # Probe URLs: only 45.79.88.1 and 45.79.88.2 (public validators).
            # Private IP 10.0.0.1 must not appear; miner IPs must not appear.
            ips_probed = [url for url in probe_log if "/scores" in url]
            assert any("45.79.88.1" in u for u in ips_probed)
            assert any("45.79.88.2" in u for u in ips_probed)
            assert not any("10.0.0.1" in u for u in ips_probed)
            assert not any("167.150.153" in u for u in ips_probed)
        finally:
            store.close()

    def test_scores_carry_validator_uid(self, client):
        body = client.get("/v1/network/miner/3").json()
        assert len(body["scores"]) >= 1
        for s in body["scores"]:
            assert "validatorUid" in s
            assert s["validatorUid"] in (0, 1)

    def test_peer_500_excluded(self, sample_nodes, monkeypatch):
        # 45.79.88.2 returns 500 → only uid 0 should appear in scores.
        c, store = _make_client(
            sample_nodes, monkeypatch, fail_scores_for={"45.79.88.2"}
        )
        try:
            body = c.get("/v1/network/miner/3").json()
            uids = [s["validatorUid"] for s in body["scores"]]
            assert 0 in uids
            assert 1 not in uids
        finally:
            store.close()

    def test_peer_found_false_excluded(self, sample_nodes, monkeypatch):
        c, store = _make_client(
            sample_nodes, monkeypatch,
            scores_payload={"uid": 3, "found": False},
        )
        try:
            body = c.get("/v1/network/miner/3").json()
            assert body["scores"] == []
        finally:
            store.close()


class TestNetworkMinerCache:
    def test_second_call_hits_cache(self, sample_nodes, monkeypatch):
        probe_log: list[str] = []
        c, store = _make_client(sample_nodes, monkeypatch, probe_log=probe_log)
        try:
            c.get("/v1/network/miner/3")
            count_after_first = len([u for u in probe_log if "/scores" in u])
            c.get("/v1/network/miner/3")
            count_after_second = len([u for u in probe_log if "/scores" in u])
            # Second call served from cache — no new probes.
            assert count_after_second == count_after_first
        finally:
            store.close()

    def test_distinct_uids_probe_independently(self, sample_nodes, monkeypatch):
        probe_log: list[str] = []
        c, store = _make_client(sample_nodes, monkeypatch, probe_log=probe_log)
        try:
            c.get("/v1/network/miner/3")
            c.get("/v1/network/miner/4")
            url_uids = set()
            for u in probe_log:
                if "/v1/miner/" in u and "/scores" in u:
                    # URL like .../v1/miner/3/scores
                    parts = u.split("/")
                    try:
                        url_uids.add(int(parts[parts.index("miner") + 1]))
                    except Exception:
                        pass
            assert url_uids == {3, 4}
        finally:
            store.close()
