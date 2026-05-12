"""Tests for /v1/hash/{path} — TLSNotary nonce challenge endpoint.

Mirrors behavior of `web/app/api/hash/[...path]/route.ts`: deterministic
SHA-256 of the URL path segment, cacheable for a year.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


@pytest.fixture
def client():
    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att)
        yield TestClient(app)
    finally:
        store.close()


def test_hash_single_path_segment(client):
    r = client.get("/v1/hash/djinn-nonce-abc123")
    assert r.status_code == 200
    body = r.json()
    assert body["input"] == "djinn-nonce-abc123"
    assert body["sha256"] == hashlib.sha256(b"djinn-nonce-abc123").hexdigest()


def test_hash_nested_path(client):
    r = client.get("/v1/hash/prefix/mid/suffix")
    assert r.status_code == 200
    body = r.json()
    assert body["input"] == "prefix/mid/suffix"
    assert body["sha256"] == hashlib.sha256(b"prefix/mid/suffix").hexdigest()


def test_hash_empty_path_is_404(client):
    # /v1/hash/ alone has no path segment; FastAPI returns 404.
    r = client.get("/v1/hash/")
    assert r.status_code == 404


def test_hash_determinism_across_requests(client):
    r1 = client.get("/v1/hash/same-nonce")
    r2 = client.get("/v1/hash/same-nonce")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_hash_different_inputs_different_outputs(client):
    r1 = client.get("/v1/hash/alpha")
    r2 = client.get("/v1/hash/beta")
    assert r1.json()["sha256"] != r2.json()["sha256"]


def test_hash_cache_header_is_immutable(client):
    r = client.get("/v1/hash/cache-test")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "immutable" in cc
    assert "max-age=31536000" in cc
