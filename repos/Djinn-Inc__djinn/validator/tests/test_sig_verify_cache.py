"""Tests for the sig-verify LRU cache (perf optimization)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from djinn_validator.api import middleware


@pytest.fixture(autouse=True)
def _clear_cache():
    middleware._SIG_VERIFY_CACHE.clear()
    yield
    middleware._SIG_VERIFY_CACHE.clear()


def test_cache_hit_skips_verify_call():
    """Same (message, sig, hotkey) tuple should be served from cache."""
    call_count = [0]

    class _MockKeypair:
        def __init__(self, *_a, **_kw):
            pass

        def verify(self, _msg, _sig):
            call_count[0] += 1
            return True

    with patch.object(middleware, "log"):
        with patch.dict("sys.modules", {"bittensor": _FakeBT(_MockKeypair)}):
            r1 = middleware.verify_hotkey_signature(b"msg", "deadbeef", "5HotkeyABC")
            r2 = middleware.verify_hotkey_signature(b"msg", "deadbeef", "5HotkeyABC")
            r3 = middleware.verify_hotkey_signature(b"msg", "deadbeef", "5HotkeyABC")
    assert r1 is True and r2 is True and r3 is True
    # Verify should run once; the next two are cache hits.
    assert call_count[0] == 1, f"expected 1 verify call, got {call_count[0]}"


def test_different_inputs_dont_collide():
    """Different (message, sig, hotkey) tuples must produce distinct entries."""
    call_count = [0]

    class _MockKeypair:
        def __init__(self, *_a, **_kw):
            pass

        def verify(self, msg, _sig):
            call_count[0] += 1
            return msg.startswith(b"good")

    with patch.dict("sys.modules", {"bittensor": _FakeBT(_MockKeypair)}):
        assert middleware.verify_hotkey_signature(b"good_a", "01", "5K1") is True
        assert middleware.verify_hotkey_signature(b"bad_b", "02", "5K2") is False
        assert middleware.verify_hotkey_signature(b"good_a", "01", "5K1") is True
        assert middleware.verify_hotkey_signature(b"bad_b", "02", "5K2") is False
    # 2 distinct keys, 2 verify calls (rest are cache hits)
    assert call_count[0] == 2


def test_cache_evicts_oldest_at_cap():
    """When cache exceeds _SIG_VERIFY_CACHE_MAX, old entries get dropped."""
    original_max = middleware._SIG_VERIFY_CACHE_MAX
    middleware._SIG_VERIFY_CACHE_MAX = 3
    try:
        for i in range(5):
            middleware._sig_cache_set((b"m", str(i), "5K"), True)
        # Cap is 3, so only the most recent 3 should remain.
        assert len(middleware._SIG_VERIFY_CACHE) == 3
        # Oldest (i=0, i=1) should be evicted; newest (i=2,3,4) present.
        assert (b"m", "0", "5K") not in middleware._SIG_VERIFY_CACHE
        assert (b"m", "4", "5K") in middleware._SIG_VERIFY_CACHE
    finally:
        middleware._SIG_VERIFY_CACHE_MAX = original_max


def test_failed_verify_is_not_cached():
    """If verify() raises, the cache should NOT pollute with False entries."""
    call_count = [0]

    class _BoomKeypair:
        def __init__(self, *_a, **_kw):
            pass

        def verify(self, _msg, _sig):
            call_count[0] += 1
            raise RuntimeError("fake transient error")

    with patch.object(middleware, "log"):
        with patch.dict("sys.modules", {"bittensor": _FakeBT(_BoomKeypair)}):
            r1 = middleware.verify_hotkey_signature(b"m", "01", "5K")
            r2 = middleware.verify_hotkey_signature(b"m", "01", "5K")
    assert r1 is False and r2 is False
    # Both calls should have invoked verify (no caching of error fallback)
    assert call_count[0] == 2, "transient errors must re-verify on next call"


class _FakeBT:
    """Tiny shim so patch.dict('sys.modules', {'bittensor': ...}) works."""

    def __init__(self, keypair_cls):
        self.Keypair = keypair_cls
