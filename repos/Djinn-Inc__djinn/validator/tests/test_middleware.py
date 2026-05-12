"""Tests for API middleware (rate limiting, auth, CORS)."""

from __future__ import annotations

import hashlib
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

import djinn_validator.api.middleware as mw_module
from djinn_validator.api.middleware import (
    API_VERSION,
    RateLimitMiddleware,
    RateLimiter,
    RequestIdMiddleware,
    TokenBucket,
    _check_nonce,
    _NONCE_CACHE,
    _SECURITY_HEADERS,
    create_signature_message,
    get_cors_origins,
    validate_signed_request,
)


class TestTokenBucket:
    def test_initial_capacity(self) -> None:
        b = TokenBucket(capacity=10, refill_rate=1)
        assert b.tokens == 10

    def test_consume_within_capacity(self) -> None:
        b = TokenBucket(capacity=5, refill_rate=1)
        for _ in range(5):
            assert b.consume() is True
        assert b.consume() is False

    def test_refill(self) -> None:
        b = TokenBucket(capacity=2, refill_rate=100)
        b.consume()
        b.consume()
        assert b.consume() is False
        # Simulate time passing
        b.last_refill = time.monotonic() - 1.0
        assert b.consume() is True


class TestRateLimiter:
    def test_allows_within_limit(self) -> None:
        limiter = RateLimiter(default_capacity=5, default_rate=1)
        for _ in range(5):
            assert limiter.allow("1.2.3.4", "/v1/signal") is True

    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(default_capacity=2, default_rate=0.001)
        limiter.allow("1.2.3.4", "/v1/signal")
        limiter.allow("1.2.3.4", "/v1/signal")
        assert limiter.allow("1.2.3.4", "/v1/signal") is False

    def test_different_ips_independent(self) -> None:
        limiter = RateLimiter(default_capacity=1, default_rate=0.001)
        assert limiter.allow("1.1.1.1", "/test") is True
        assert limiter.allow("2.2.2.2", "/test") is True
        assert limiter.allow("1.1.1.1", "/test") is False

    def test_path_specific_limits(self) -> None:
        limiter = RateLimiter(default_capacity=10, default_rate=10)
        limiter.set_path_limit("/v1/mpc/", capacity=2, rate=0.001)
        # MPC path limited to 2
        assert limiter.allow("1.1.1.1", "/v1/mpc/init") is True
        assert limiter.allow("1.1.1.1", "/v1/mpc/init") is True
        assert limiter.allow("1.1.1.1", "/v1/mpc/init") is False
        # Default path still has capacity
        assert limiter.allow("1.1.1.1", "/v1/signal") is True


class TestRateLimitMiddleware:
    @pytest.fixture
    def limited_app(self) -> TestClient:
        app = FastAPI()
        limiter = RateLimiter(default_capacity=3, default_rate=0.001)
        app.add_middleware(RateLimitMiddleware, limiter=limiter)

        @app.get("/test")
        async def test_ep() -> dict:
            return {"ok": True}

        @app.get("/health")
        async def health() -> dict:
            return {"status": "ok"}

        @app.get("/health/ready")
        async def readiness() -> dict:
            return {"ready": True}

        return TestClient(app)

    def test_allows_requests(self, limited_app: TestClient) -> None:
        resp = limited_app.get("/test")
        assert resp.status_code == 200

    def test_rate_limits(self, limited_app: TestClient) -> None:
        for _ in range(3):
            limited_app.get("/test")
        resp = limited_app.get("/test")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_health_bypasses_limit(self, limited_app: TestClient) -> None:
        # Exhaust limit on /test
        for _ in range(3):
            limited_app.get("/test")
        # Health check still works
        resp = limited_app.get("/health")
        assert resp.status_code == 200

    def test_readiness_bypasses_limit(self, limited_app: TestClient) -> None:
        for _ in range(3):
            limited_app.get("/test")
        resp = limited_app.get("/health/ready")
        assert resp.status_code == 200


class TestRateLimiterBoundary:
    def test_exact_boundary_enforcement(self) -> None:
        """Request N+1 should be rejected when capacity is N."""
        limiter = RateLimiter(default_capacity=20, default_rate=0.001)
        for i in range(20):
            assert limiter.allow("1.1.1.1", "/v1/signal") is True, f"Request {i + 1} should pass"
        assert limiter.allow("1.1.1.1", "/v1/signal") is False, "Request 21 should be blocked"

    def test_path_specific_boundary(self) -> None:
        """Path-specific limits are enforced at their boundary."""
        limiter = RateLimiter(default_capacity=100, default_rate=100)
        limiter.set_path_limit("/v1/signal", capacity=5, rate=0.001)
        for i in range(5):
            assert limiter.allow("1.1.1.1", "/v1/signal/store") is True
        assert limiter.allow("1.1.1.1", "/v1/signal/store") is False
        # Default path still has capacity
        assert limiter.allow("1.1.1.1", "/v1/mpc/init") is True

    def test_cleanup_under_pressure(self) -> None:
        """When bucket count exceeds MAX_BUCKETS, cleanup runs."""
        limiter = RateLimiter(default_capacity=5, default_rate=1)
        # Fill beyond MAX_BUCKETS (default 10000) — but just verify the method doesn't crash
        for i in range(100):
            limiter.allow(f"10.0.0.{i % 256}", f"/path/{i}")
        # Force cleanup
        limiter._last_cleanup = 0
        limiter._maybe_cleanup()
        # Should not crash


class TestCorsOrigins:
    def test_empty_returns_wildcard(self) -> None:
        assert get_cors_origins("") == ["*"]

    def test_single_origin(self) -> None:
        assert get_cors_origins("https://djinn.io") == ["https://djinn.io"]

    def test_multiple_origins(self) -> None:
        result = get_cors_origins("https://djinn.io, https://app.djinn.io")
        assert result == ["https://djinn.io", "https://app.djinn.io"]

    def test_strips_whitespace(self) -> None:
        result = get_cors_origins("  https://a.com , https://b.com  ")
        assert result == ["https://a.com", "https://b.com"]

    def test_filters_empty_values(self) -> None:
        result = get_cors_origins("https://a.com,,, ,https://b.com")
        assert result == ["https://a.com", "https://b.com"]

    def test_trailing_comma(self) -> None:
        result = get_cors_origins("https://a.com,")
        assert result == ["https://a.com"]

    def test_production_rejects_wildcard(self) -> None:
        with pytest.raises(ValueError, match="CORS_ORIGINS must be set"):
            get_cors_origins("", bt_network="finney")

    def test_production_mainnet_rejects_wildcard(self) -> None:
        with pytest.raises(ValueError, match="CORS_ORIGINS must be set"):
            get_cors_origins("", bt_network="mainnet")

    def test_production_with_origins_succeeds(self) -> None:
        result = get_cors_origins("https://djinn.io", bt_network="finney")
        assert result == ["https://djinn.io"]

    def test_dev_network_allows_wildcard(self) -> None:
        result = get_cors_origins("", bt_network="test")
        assert result == ["*"]


class TestSignatureMessage:
    def test_message_format(self) -> None:
        msg = create_signature_message("/v1/mpc/init", "abc123", 1700000000, "nonce1")
        assert msg == b"/v1/mpc/init:abc123:1700000000:nonce1"


class TestValidateSignedRequest:
    """Test auth validation.

    In dev mode (no bittensor, no auth headers), validation is skipped.
    With auth headers, timestamp freshness and header completeness are checked.
    """

    @pytest.fixture
    def auth_app(self) -> TestClient:
        app = FastAPI()

        @app.post("/v1/mpc/test")
        async def mpc_test(request: Request) -> dict:
            hotkey = await validate_signed_request(request)
            return {"hotkey": hotkey}

        return TestClient(app)

    def test_no_auth_headers_skipped(self, auth_app: TestClient) -> None:
        """In dev mode (no auth headers), request passes through."""
        resp = auth_app.post("/v1/mpc/test", json={})
        assert resp.status_code == 200
        assert resp.json()["hotkey"] is None

    def test_partial_auth_headers_rejected(self, auth_app: TestClient) -> None:
        """If some auth headers present but not all, reject."""
        resp = auth_app.post(
            "/v1/mpc/test",
            json={},
            headers={"X-Hotkey": "5FakeKey"},
        )
        assert resp.status_code == 401

    def test_stale_timestamp_rejected(self, auth_app: TestClient) -> None:
        resp = auth_app.post(
            "/v1/mpc/test",
            json={},
            headers={
                "X-Hotkey": "5FakeKey",
                "X-Signature": "abcd",
                "X-Timestamp": str(int(time.time()) - 120),  # 2 min ago
                "X-Nonce": "test",
            },
        )
        assert resp.status_code == 401
        assert "too old" in resp.json()["detail"]

    def test_invalid_timestamp_format_rejected(self, auth_app: TestClient) -> None:
        resp = auth_app.post(
            "/v1/mpc/test",
            json={},
            headers={
                "X-Hotkey": "5FakeKey",
                "X-Signature": "abcd",
                "X-Timestamp": "not-a-number",
                "X-Nonce": "test",
            },
        )
        assert resp.status_code == 401
        assert "Invalid timestamp" in resp.json()["detail"]

    def test_forbidden_hotkey_rejected(self) -> None:
        """Hotkey not in allowlist should be rejected."""
        app = FastAPI()

        @app.post("/v1/mpc/test")
        async def mpc_test(request: Request) -> dict:
            hotkey = await validate_signed_request(request, allowed_hotkeys={"5AllowedKey"})
            return {"hotkey": hotkey}

        client = TestClient(app)
        resp = client.post(
            "/v1/mpc/test",
            json={},
            headers={
                "X-Hotkey": "5ForbiddenKey",
                "X-Signature": "abcd",
                "X-Timestamp": str(int(time.time())),
                "X-Nonce": "test",
            },
        )
        assert resp.status_code == 403


class TestTokenBucketEdgeCases:
    def test_capacity_does_not_overflow(self) -> None:
        """Refill should not exceed initial capacity."""
        b = TokenBucket(capacity=5, refill_rate=1000)
        b.last_refill = time.monotonic() - 100
        assert b.consume() is True
        assert b.tokens <= 5.0

    def test_consume_multiple_tokens(self) -> None:
        b = TokenBucket(capacity=10, refill_rate=1)
        assert b.consume(5) is True
        assert b.consume(5) is True
        assert b.consume(1) is False


class TestRateLimiterStaleCleanup:
    def test_stale_bucket_cleanup(self) -> None:
        limiter = RateLimiter(default_capacity=5, default_rate=1)
        limiter.allow("1.1.1.1", "/test")
        # Make stale
        for key in list(limiter._buckets.keys()):
            limiter._buckets[key].last_refill = time.monotonic() - 600
        limiter._last_cleanup = time.monotonic() - 600
        limiter._maybe_cleanup()
        assert len(limiter._buckets) == 0

    def test_cleanup_keeps_fresh_buckets(self) -> None:
        limiter = RateLimiter(default_capacity=5, default_rate=1)
        limiter.allow("fresh", "/test")
        limiter.allow("stale", "/test")
        for key in limiter._buckets:
            if "stale" in key:
                limiter._buckets[key].last_refill = time.monotonic() - 600
        limiter._last_cleanup = time.monotonic() - 600
        limiter._maybe_cleanup()
        assert any("fresh" in k for k in limiter._buckets)
        assert not any("stale" in k for k in limiter._buckets)


class TestBucketOverflowEviction:
    def test_overflow_evicts_to_max(self) -> None:
        """When bucket count exceeds MAX, eviction brings it back to MAX."""
        limiter = RateLimiter(default_capacity=5, default_rate=1)
        limiter._MAX_BUCKETS = 10  # Lower for testing
        # Fill up
        for i in range(15):
            limiter.allow(f"ip-{i}", "/test")
        # Force cleanup (make all buckets stale so cleanup triggers eviction path)
        limiter._last_cleanup = 0
        limiter._maybe_cleanup()
        assert len(limiter._buckets) <= 10


class TestNonceReplay:
    def setup_method(self) -> None:
        _NONCE_CACHE.clear()

    def test_fresh_nonce_accepted(self) -> None:
        assert _check_nonce("nonce-fresh-1") is True

    def test_replayed_nonce_rejected(self) -> None:
        _check_nonce("nonce-replay-1")
        assert _check_nonce("nonce-replay-1") is False

    def test_different_nonces_accepted(self) -> None:
        assert _check_nonce("a") is True
        assert _check_nonce("b") is True
        assert _check_nonce("c") is True

    def test_nonce_periodic_cleanup(self) -> None:
        """Stale nonces are evicted after cleanup interval elapses."""
        # Insert a nonce with an old timestamp
        _NONCE_CACHE["old-nonce"] = time.time() - 300  # 5 minutes ago
        _NONCE_CACHE["fresh-nonce"] = time.time()
        # Force cleanup by setting last cleanup time far in the past
        mw_module._NONCE_LAST_CLEANUP = 0.0
        # Calling _check_nonce triggers periodic cleanup
        _check_nonce("trigger-cleanup")
        assert "old-nonce" not in _NONCE_CACHE, "Stale nonce should be evicted"
        assert "fresh-nonce" in _NONCE_CACHE, "Fresh nonce should be kept"

    def test_nonce_replay_in_auth_flow(self) -> None:
        """Full auth flow rejects replayed nonces."""
        app = FastAPI()

        @app.post("/v1/mpc/test")
        async def mpc_test(request: Request) -> dict:
            hotkey = await validate_signed_request(request)
            return {"hotkey": hotkey}

        client = TestClient(app)
        ts = str(int(time.time()))
        headers = {
            "X-Hotkey": "5FakeKey",
            "X-Signature": "abcd",
            "X-Timestamp": ts,
            "X-Nonce": "unique-nonce-1",
        }
        # First request — nonce check passes (may fail on signature, that's fine)
        resp1 = client.post("/v1/mpc/test", json={}, headers=headers)
        # Second request with same nonce — should be rejected with 401
        resp2 = client.post("/v1/mpc/test", json={}, headers=headers)
        assert resp2.status_code == 401
        assert "Nonce already used" in resp2.json()["detail"]

    def test_nonce_thread_safety(self) -> None:
        """Concurrent nonce checks don't corrupt state."""
        import threading

        _NONCE_CACHE.clear()
        results: list[bool] = []
        errors: list[Exception] = []

        def check_many(prefix: str, count: int) -> None:
            for i in range(count):
                try:
                    results.append(_check_nonce(f"{prefix}-{i}"))
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=check_many, args=(f"t{t}", 100)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert len(results) == 500
        assert all(r is True for r in results), "All unique nonces should be accepted"


class TestSecurityHeaders:
    @pytest.fixture
    def header_app(self) -> TestClient:
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict:
            return {"ok": True}

        return TestClient(app)

    def test_api_version_header_set(self, header_app: TestClient) -> None:
        resp = header_app.get("/test")
        assert resp.headers.get("X-API-Version") == API_VERSION

    def test_security_headers_present(self, header_app: TestClient) -> None:
        resp = header_app.get("/test")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_request_id_header_set(self, header_app: TestClient) -> None:
        resp = header_app.get("/test")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0

    def test_forwarded_request_id_preserved(self, header_app: TestClient) -> None:
        resp = header_app.get("/test", headers={"X-Request-ID": "custom-id-123"})
        assert resp.headers["X-Request-ID"] == "custom-id-123"


class TestVersionConsistency:
    def test_api_version_matches_package(self) -> None:
        from djinn_validator import __version__

        assert API_VERSION == __version__
