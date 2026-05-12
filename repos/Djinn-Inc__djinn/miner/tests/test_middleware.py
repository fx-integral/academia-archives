"""Tests for miner API middleware (rate limiting, request ID, CORS)."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from djinn_miner.api.middleware import (
    RateLimitMiddleware,
    RateLimiter,
    RequestIdMiddleware,
    TokenBucket,
    get_cors_origins,
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
        limiter = RateLimiter(capacity=5, rate=1)
        for _ in range(5):
            assert limiter.allow("1.2.3.4") is True

    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(capacity=2, rate=0.001)
        limiter.allow("1.2.3.4")
        limiter.allow("1.2.3.4")
        assert limiter.allow("1.2.3.4") is False

    def test_different_ips_independent(self) -> None:
        limiter = RateLimiter(capacity=1, rate=0.001)
        assert limiter.allow("1.1.1.1") is True
        assert limiter.allow("2.2.2.2") is True
        assert limiter.allow("1.1.1.1") is False

    def test_evict_oldest_when_full(self) -> None:
        limiter = RateLimiter(capacity=10, rate=10)
        limiter._MAX_BUCKETS = 3
        limiter.allow("1.1.1.1")
        limiter.allow("2.2.2.2")
        limiter.allow("3.3.3.3")
        # 4th IP should trigger eviction of oldest
        limiter.allow("4.4.4.4")
        assert len(limiter._buckets) <= 3

    def test_stale_bucket_cleanup(self) -> None:
        limiter = RateLimiter(capacity=5, rate=1)
        limiter.allow("1.1.1.1")
        # Simulate stale bucket
        limiter._buckets["1.1.1.1"].last_refill = time.monotonic() - 600
        limiter._last_cleanup = time.monotonic() - 600
        limiter._maybe_cleanup()
        assert "1.1.1.1" not in limiter._buckets


class TestRateLimitMiddleware:
    @pytest.fixture
    def limited_app(self) -> TestClient:
        app = FastAPI()
        limiter = RateLimiter(capacity=3, rate=0.001)
        app.add_middleware(RateLimitMiddleware, limiter=limiter)

        @app.get("/test")
        async def test_ep() -> dict:
            return {"ok": True}

        @app.get("/health")
        async def health() -> dict:
            return {"status": "ok"}

        @app.get("/metrics")
        async def metrics() -> dict:
            return {"metrics": True}

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
        for _ in range(3):
            limited_app.get("/test")
        resp = limited_app.get("/health")
        assert resp.status_code == 200

    def test_metrics_bypasses_limit(self, limited_app: TestClient) -> None:
        for _ in range(3):
            limited_app.get("/test")
        resp = limited_app.get("/metrics")
        assert resp.status_code == 200

    def test_readiness_bypasses_limit(self, limited_app: TestClient) -> None:
        for _ in range(3):
            limited_app.get("/test")
        resp = limited_app.get("/health/ready")
        assert resp.status_code == 200


class TestRequestIdMiddleware:
    @pytest.fixture
    def traced_app(self) -> TestClient:
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/test")
        async def test_ep() -> dict:
            return {"ok": True}

        return TestClient(app)

    def test_generates_request_id(self, traced_app: TestClient) -> None:
        resp = traced_app.get("/test")
        assert "x-request-id" in resp.headers
        assert len(resp.headers["x-request-id"]) == 32

    def test_forwards_existing_request_id(self, traced_app: TestClient) -> None:
        resp = traced_app.get("/test", headers={"X-Request-ID": "my-trace-abc"})
        assert resp.headers["x-request-id"] == "my-trace-abc"

    def test_unique_ids_per_request(self, traced_app: TestClient) -> None:
        r1 = traced_app.get("/test")
        r2 = traced_app.get("/test")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


class TestCorsOrigins:
    def test_empty_returns_wildcard(self) -> None:
        assert get_cors_origins("") == ["*"]

    def test_single_origin(self) -> None:
        assert get_cors_origins("https://djinn.io") == ["https://djinn.io"]

    def test_multiple_origins(self) -> None:
        result = get_cors_origins("https://djinn.io, https://app.djinn.io")
        assert result == ["https://djinn.io", "https://app.djinn.io"]

    def test_strips_whitespace(self) -> None:
        result = get_cors_origins("  https://a.io  ,  https://b.io  ")
        assert result == ["https://a.io", "https://b.io"]

    def test_ignores_empty_entries(self) -> None:
        result = get_cors_origins("https://a.io,,https://b.io")
        assert result == ["https://a.io", "https://b.io"]

    def test_trailing_comma(self) -> None:
        result = get_cors_origins("https://a.io,")
        assert result == ["https://a.io"]

    def test_production_requires_cors_origins(self) -> None:
        with pytest.raises(ValueError, match="CORS_ORIGINS must be set"):
            get_cors_origins("", bt_network="finney")

    def test_production_with_origins_ok(self) -> None:
        result = get_cors_origins("https://djinn.io", bt_network="finney")
        assert result == ["https://djinn.io"]


class TestTokenBucketEdgeCases:
    def test_capacity_does_not_overflow(self) -> None:
        """Refill should not exceed initial capacity."""
        b = TokenBucket(capacity=5, refill_rate=1000)
        b.last_refill = time.monotonic() - 100  # 100 seconds = 100k tokens @ rate 1000
        assert b.consume() is True
        assert b.tokens <= 5.0

    def test_consume_multiple_tokens(self) -> None:
        b = TokenBucket(capacity=10, refill_rate=1)
        assert b.consume(5) is True
        assert b.consume(5) is True
        assert b.consume(1) is False

    def test_zero_rate_bucket(self) -> None:
        """With zero refill rate, tokens never recover."""
        b = TokenBucket(capacity=1, refill_rate=0)
        assert b.consume() is True
        b.last_refill = time.monotonic() - 1000
        assert b.consume() is False


class TestRateLimiterCleanup:
    def test_cleanup_removes_stale_keeps_fresh(self) -> None:
        limiter = RateLimiter(capacity=5, rate=1)
        limiter.allow("fresh-ip")
        limiter.allow("stale-ip")
        limiter._buckets["stale-ip"].last_refill = time.monotonic() - 600
        limiter._last_cleanup = time.monotonic() - 600
        limiter._maybe_cleanup()
        assert "stale-ip" not in limiter._buckets
        assert "fresh-ip" in limiter._buckets

    def test_cleanup_skipped_when_recent(self) -> None:
        limiter = RateLimiter(capacity=5, rate=1)
        limiter.allow("1.1.1.1")
        limiter._buckets["1.1.1.1"].last_refill = time.monotonic() - 600  # stale
        # Don't force cleanup time
        limiter._maybe_cleanup()
        assert "1.1.1.1" in limiter._buckets  # Not cleaned because interval not reached


class TestEvictOldestGuard:
    def test_evict_oldest_on_empty_dict(self) -> None:
        """_evict_oldest should not crash on empty buckets dict."""
        limiter = RateLimiter(capacity=5, rate=1)
        limiter._buckets.clear()
        limiter._evict_oldest()  # Should not raise


class TestVersionConsistency:
    def test_api_version_matches_package(self) -> None:
        from djinn_miner import __version__
        from djinn_miner.api.middleware import API_VERSION

        assert API_VERSION == __version__
