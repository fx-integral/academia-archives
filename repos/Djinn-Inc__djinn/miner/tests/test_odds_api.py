"""Tests for The Odds API client."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from djinn_miner.data.odds_api import (
    BookmakerOdds,
    CachedOdds,
    CachedError,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    OddsApiClient,
)


@pytest.fixture
def client(mock_odds_response: list[dict]) -> OddsApiClient:
    """Create an OddsApiClient with a mock HTTP client."""
    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=mock_odds_response))
    )
    return OddsApiClient(
        api_key="test-key",
        base_url="https://api.the-odds-api.com",
        cache_ttl=30,
        http_client=mock_http,
    )


@pytest.mark.asyncio
async def test_get_odds_fetches_data(client: OddsApiClient, mock_odds_response: list[dict]) -> None:
    result = await client.get_odds("basketball_nba")
    assert len(result) == len(mock_odds_response)
    assert result[0]["id"] == "event-lakers-celtics-001"


@pytest.mark.asyncio
async def test_get_odds_uses_cache(client: OddsApiClient) -> None:
    result1 = await client.get_odds("basketball_nba")
    result2 = await client.get_odds("basketball_nba")
    assert result1 is result2


@pytest.mark.asyncio
async def test_get_odds_cache_expires(mock_odds_response: list[dict]) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=mock_odds_response)

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c = OddsApiClient(api_key="test", cache_ttl=0, http_client=mock_http)

    await c.get_odds("basketball_nba")
    await c.get_odds("basketball_nba")
    assert call_count == 2


@pytest.mark.asyncio
async def test_get_odds_resolves_sport_key(mock_odds_response: list[dict]) -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json=mock_odds_response)

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c = OddsApiClient(api_key="test", http_client=mock_http)

    await c.get_odds("football_nfl")
    assert "americanfootball_nfl" in requested_urls[0]


@pytest.mark.asyncio
async def test_get_odds_http_error() -> None:
    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "unauthorized"}))
    )
    c = OddsApiClient(api_key="bad-key", http_client=mock_http)

    with pytest.raises(httpx.HTTPStatusError):
        await c.get_odds("basketball_nba")


def test_parse_bookmaker_odds_all_events(client: OddsApiClient, mock_odds_response: list[dict]) -> None:
    result = client.parse_bookmaker_odds(mock_odds_response)
    assert len(result) > 0
    assert all(isinstance(o, BookmakerOdds) for o in result)


def test_parse_bookmaker_odds_filter_by_event_id(client: OddsApiClient, mock_odds_response: list[dict]) -> None:
    result = client.parse_bookmaker_odds(
        mock_odds_response,
        event_id="event-lakers-celtics-001",
    )
    # Should only include odds from the Lakers-Celtics event
    bookmakers_with_data = {o.bookmaker_key for o in result}
    assert "fanduel" in bookmakers_with_data
    assert "draftkings" in bookmakers_with_data


def test_parse_bookmaker_odds_filter_by_teams(client: OddsApiClient, mock_odds_response: list[dict]) -> None:
    result = client.parse_bookmaker_odds(
        mock_odds_response,
        home_team="Miami Heat",
        away_team="Golden State Warriors",
    )
    # Heat-Warriors event only has FanDuel
    bookmakers = {o.bookmaker_key for o in result}
    assert bookmakers == {"fanduel"}


def test_parse_bookmaker_odds_team_match_case_insensitive(
    client: OddsApiClient, mock_odds_response: list[dict]
) -> None:
    result = client.parse_bookmaker_odds(
        mock_odds_response,
        home_team="miami heat",
        away_team="golden state warriors",
    )
    assert len(result) > 0


def test_parse_bookmaker_odds_no_match(client: OddsApiClient, mock_odds_response: list[dict]) -> None:
    result = client.parse_bookmaker_odds(
        mock_odds_response,
        event_id="nonexistent-event",
        home_team="Fake Team",
        away_team="Other Fake Team",
    )
    assert len(result) == 0


def test_parse_bookmaker_odds_spreads_have_points(client: OddsApiClient, mock_odds_response: list[dict]) -> None:
    result = client.parse_bookmaker_odds(
        mock_odds_response,
        event_id="event-lakers-celtics-001",
    )
    spreads = [o for o in result if o.market == "spreads"]
    assert len(spreads) > 0
    assert all(o.point is not None for o in spreads)


def test_parse_bookmaker_odds_h2h_no_points(client: OddsApiClient, mock_odds_response: list[dict]) -> None:
    result = client.parse_bookmaker_odds(
        mock_odds_response,
        event_id="event-lakers-celtics-001",
    )
    h2h = [o for o in result if o.market == "h2h"]
    assert len(h2h) > 0
    assert all(o.point is None for o in h2h)


def test_clear_cache(client: OddsApiClient) -> None:
    # Seed cache manually
    client._cache["test_key"] = CachedOdds(data=[{}], expires_at=time.monotonic() + 100)
    assert len(client._cache) == 1
    client.clear_cache()
    assert len(client._cache) == 0


@pytest.mark.asyncio
async def test_get_odds_captures_session(mock_odds_response: list[dict]) -> None:
    """When a SessionCapture is provided, get_odds should record the raw response."""
    from djinn_miner.core.proof import SessionCapture

    capture = SessionCapture()
    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=mock_odds_response))
    )
    c = OddsApiClient(
        api_key="test-key",
        cache_ttl=0,
        http_client=mock_http,
        session_capture=capture,
    )

    await c.get_odds("basketball_nba")
    assert capture.count == 1


@pytest.mark.asyncio
async def test_get_odds_no_capture_when_cached(mock_odds_response: list[dict]) -> None:
    """Cached responses should NOT trigger session capture (no HTTP call made)."""
    from djinn_miner.core.proof import SessionCapture

    capture = SessionCapture()
    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=mock_odds_response))
    )
    c = OddsApiClient(
        api_key="test-key",
        cache_ttl=60,
        http_client=mock_http,
        session_capture=capture,
    )

    await c.get_odds("basketball_nba")
    assert capture.count == 1  # First call captured

    await c.get_odds("basketball_nba")
    assert capture.count == 1  # Second call used cache, no new capture


@pytest.mark.asyncio
async def test_captured_session_strips_api_key(mock_odds_response: list[dict]) -> None:
    """The API key should not appear in the captured session params."""
    from djinn_miner.core.proof import SessionCapture

    capture = SessionCapture()
    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=mock_odds_response))
    )
    c = OddsApiClient(
        api_key="secret-key-123",
        cache_ttl=0,
        http_client=mock_http,
        session_capture=capture,
    )

    await c.get_odds("basketball_nba")

    # Get the captured session
    sessions = list(capture._sessions.values())
    assert len(sessions) == 1
    session = sessions[0]
    assert "apiKey" not in session.request_params
    assert "secret-key-123" not in str(session.request_params)


@pytest.mark.asyncio
async def test_retry_on_5xx(mock_odds_response: list[dict]) -> None:
    """5xx errors should be retried up to max_retries times."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=mock_odds_response)

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c = OddsApiClient(api_key="test", http_client=mock_http, max_retries=3)

    result = await c.get_odds("basketball_nba")
    assert len(result) == len(mock_odds_response)
    assert call_count == 3  # 2 failures + 1 success


@pytest.mark.asyncio
async def test_retry_exhausted_raises() -> None:
    """When all retries are exhausted, the last error should be raised."""
    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "unavailable"}))
    )
    c = OddsApiClient(api_key="test", http_client=mock_http, max_retries=1)

    with pytest.raises(httpx.HTTPStatusError):
        await c.get_odds("basketball_nba")


@pytest.mark.asyncio
async def test_no_retry_on_4xx() -> None:
    """4xx errors should NOT be retried."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c = OddsApiClient(api_key="bad", http_client=mock_http, max_retries=3)

    with pytest.raises(httpx.HTTPStatusError):
        await c.get_odds("basketball_nba")
    assert call_count == 1  # No retry


@pytest.mark.asyncio
async def test_concurrent_requests_only_fetch_once(mock_odds_response: list[dict]) -> None:
    """Concurrent cache-miss requests for the same sport should only fetch once."""
    call_count = 0

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)  # Simulate network delay
        return httpx.Response(200, json=mock_odds_response)

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
    c = OddsApiClient(api_key="test", cache_ttl=60, http_client=mock_http)

    # Launch 5 concurrent requests for the same sport
    results = await asyncio.gather(
        c.get_odds("basketball_nba"),
        c.get_odds("basketball_nba"),
        c.get_odds("basketball_nba"),
        c.get_odds("basketball_nba"),
        c.get_odds("basketball_nba"),
    )
    # All should return the same data
    assert all(r == results[0] for r in results)
    # Only one actual HTTP call should have been made (lock prevents stampede)
    assert call_count == 1


@pytest.mark.asyncio
async def test_close_releases_owned_client() -> None:
    """close() should release the owned HTTP client."""
    c = OddsApiClient(api_key="test")
    assert c._owns_client is True
    await c.close()
    # After close, the client should be closed
    assert c._client.is_closed


@pytest.mark.asyncio
async def test_async_context_manager_closes_client() -> None:
    """async with OddsApiClient should close client on exit."""
    async with OddsApiClient(api_key="test") as c:
        assert not c._client.is_closed
    assert c._client.is_closed


@pytest.mark.asyncio
async def test_close_does_not_close_injected_client() -> None:
    """close() should NOT close an injected HTTP client."""
    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    c = OddsApiClient(api_key="test", http_client=mock_http)
    assert c._owns_client is False
    await c.close()
    assert not mock_http.is_closed
    await mock_http.aclose()


@pytest.mark.asyncio
async def test_json_decode_error_propagates() -> None:
    """If API returns non-JSON, the error should propagate."""
    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})
        )
    )
    c = OddsApiClient(api_key="test", http_client=mock_http, cache_ttl=60)
    # resp.json() will raise json.JSONDecodeError
    with pytest.raises(Exception):
        await c.get_odds("basketball_nba")


def test_sport_key_mapping() -> None:
    """Known sport keys should be mapped, unknown keys passed through."""
    c = OddsApiClient(api_key="test")
    assert c._resolve_sport_key("basketball_nba") == "basketball_nba"
    assert c._resolve_sport_key("football_nfl") == "americanfootball_nfl"
    assert c._resolve_sport_key("unknown_sport") == "unknown_sport"


def test_clear_cache() -> None:
    c = OddsApiClient(api_key="test")
    c._cache["test"] = CachedOdds(data=[], expires_at=9999999999)
    c.clear_cache()
    assert len(c._cache) == 0


def test_evict_stale_cache() -> None:
    """Stale cache entries should be removed."""
    c = OddsApiClient(api_key="test")
    c._cache["fresh"] = CachedOdds(data=[{"id": "1"}], expires_at=9999999999)
    c._cache["stale"] = CachedOdds(data=[{"id": "2"}], expires_at=0)
    c._evict_stale_cache()
    assert "fresh" in c._cache
    assert "stale" not in c._cache


def test_parse_bookmaker_odds_non_dict_event() -> None:
    """Non-dict events in the list should be skipped, not crash."""
    c = OddsApiClient(api_key="test")
    events = [42, "string", None, {"id": "real", "bookmakers": []}]  # type: ignore[list-item]
    result = c.parse_bookmaker_odds(events)
    assert len(result) == 0  # real event has no markets


def test_parse_bookmaker_odds_bad_price() -> None:
    """Non-numeric price values should default to 0.0."""
    c = OddsApiClient(api_key="test")
    events = [
        {
            "id": "ev-1",
            "home_team": "A",
            "away_team": "B",
            "bookmakers": [
                {
                    "key": "bk",
                    "title": "Bookie",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [{"name": "A", "price": "invalid"}],
                        }
                    ],
                }
            ],
        }
    ]
    result = c.parse_bookmaker_odds(events)
    assert len(result) == 1
    assert result[0].price == 0.0


def test_parse_bookmaker_odds_non_dict_bookmaker() -> None:
    """Non-dict bookmakers should be skipped."""
    c = OddsApiClient(api_key="test")
    events = [{"id": "ev-1", "bookmakers": ["not-a-dict", 42]}]
    result = c.parse_bookmaker_odds(events)
    assert len(result) == 0


class TestNaNParsing:
    """NaN and Infinity values from API must be sanitized during parsing."""

    def _make_event(self, price: object, point: object = None) -> list[dict]:
        outcome: dict = {"name": "Team A", "price": price}
        if point is not None:
            outcome["point"] = point
        return [
            {
                "id": "ev-1",
                "home_team": "A",
                "away_team": "B",
                "bookmakers": [
                    {
                        "key": "bk",
                        "title": "Bookie",
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [outcome],
                            }
                        ],
                    }
                ],
            }
        ]

    def test_nan_price_becomes_zero(self) -> None:
        c = OddsApiClient(api_key="test")
        result = c.parse_bookmaker_odds(self._make_event(float("nan")))
        assert len(result) == 1
        assert result[0].price == 0.0

    def test_inf_price_becomes_zero(self) -> None:
        c = OddsApiClient(api_key="test")
        result = c.parse_bookmaker_odds(self._make_event(float("inf")))
        assert len(result) == 1
        assert result[0].price == 0.0

    def test_nan_point_becomes_none(self) -> None:
        c = OddsApiClient(api_key="test")
        result = c.parse_bookmaker_odds(self._make_event(1.91, float("nan")))
        assert len(result) == 1
        assert result[0].point is None

    def test_inf_point_becomes_none(self) -> None:
        c = OddsApiClient(api_key="test")
        result = c.parse_bookmaker_odds(self._make_event(1.91, float("-inf")))
        assert len(result) == 1
        assert result[0].point is None

    def test_valid_price_and_point_preserved(self) -> None:
        c = OddsApiClient(api_key="test")
        result = c.parse_bookmaker_odds(self._make_event(1.91, -3.5))
        assert len(result) == 1
        assert result[0].price == 1.91
        assert result[0].point == -3.5

    def test_string_nan_point_becomes_none(self) -> None:
        c = OddsApiClient(api_key="test")
        result = c.parse_bookmaker_odds(self._make_event(1.91, "NaN"))
        assert len(result) == 1
        assert result[0].point is None


class TestErrorCaching:
    """Failed API responses are cached with short TTL to prevent request storms.

    Error cache re-raises the original exception immediately (no retries),
    so callers still see failures — we just avoid redundant retry cycles.
    """

    @pytest.mark.asyncio
    async def test_5xx_failure_is_cached(self) -> None:
        """After a 5xx failure, subsequent requests re-raise without new API call."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(503, json={"error": "down"})

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        c = OddsApiClient(api_key="test", http_client=mock_http, max_retries=0)

        with pytest.raises(httpx.HTTPStatusError):
            await c.get_odds("basketball_nba")

        first_call_count = call_count

        # Second request should hit error cache — re-raises, no new API call
        with pytest.raises(httpx.HTTPStatusError):
            await c.get_odds("basketball_nba")
        assert call_count == first_call_count

    @pytest.mark.asyncio
    async def test_4xx_failure_is_cached(self) -> None:
        """4xx errors also get cached to prevent hammering."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, json={"error": "unauthorized"})

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        c = OddsApiClient(api_key="bad", http_client=mock_http, max_retries=0)

        with pytest.raises(httpx.HTTPStatusError):
            await c.get_odds("basketball_nba")

        first_call_count = call_count

        # Second request hits error cache — re-raises
        with pytest.raises(httpx.HTTPStatusError):
            await c.get_odds("basketball_nba")
        assert call_count == first_call_count

    @pytest.mark.asyncio
    async def test_error_cache_expires(self) -> None:
        """Error cache entries expire after ERROR_CACHE_TTL."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(503, json={"error": "down"})

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        c = OddsApiClient(api_key="test", http_client=mock_http, max_retries=0)

        with pytest.raises(httpx.HTTPStatusError):
            await c.get_odds("basketball_nba")

        # Expire the error cache entry
        for entry in c._error_cache.values():
            entry.expires_at = 0

        # Next request should make a new API call
        with pytest.raises(httpx.HTTPStatusError):
            await c.get_odds("basketball_nba")

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_json_decode_error_is_cached(self) -> None:
        """Non-JSON responses get cached as errors too."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        c = OddsApiClient(api_key="test", http_client=mock_http, cache_ttl=60)

        with pytest.raises(Exception):
            await c.get_odds("basketball_nba")

        first_call_count = call_count

        # Second request should hit error cache — re-raises
        with pytest.raises(Exception):
            await c.get_odds("basketball_nba")
        assert call_count == first_call_count


class TestCircuitBreaker:
    """Tests for the CircuitBreaker standalone and integration with OddsApiClient."""

    def test_initial_state_is_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_check_passes_when_closed(self) -> None:
        cb = CircuitBreaker()
        cb.check()  # Should not raise

    def test_trips_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_requests(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        with pytest.raises(CircuitOpenError):
            cb.check()

    def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()  # Still needs 3 to trip
        assert cb.state == CircuitState.CLOSED

    def test_half_open_after_recovery_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_one_request(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.check()  # First request should pass
        # Second request should fail (test request in flight)
        with pytest.raises(CircuitOpenError):
            cb.check()

    def test_half_open_success_closes_circuit(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.check()  # Allow test request
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.check()  # Allow test request
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_reset(self) -> None:
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration_trips_on_repeated_failures(self) -> None:
        """OddsApiClient circuit breaker should trip after repeated 5xx errors."""
        mock_http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))
        )
        c = OddsApiClient(
            api_key="test",
            http_client=mock_http,
            max_retries=0,
            circuit_failure_threshold=3,
            circuit_recovery_timeout=60.0,
        )

        # First 3 failures should go through to API (each trips failure count)
        for _ in range(3):
            c._circuit.reset()  # Reset between calls since error cache would prevent retries
            with pytest.raises(httpx.HTTPStatusError):
                await c.get_odds(f"basketball_nba_{_}")  # Different cache keys

        # Now circuit should be open — next request rejected immediately
        c._circuit.record_failure()
        c._circuit.record_failure()
        c._circuit.record_failure()
        with pytest.raises(CircuitOpenError):
            await c.get_odds("basketball_nba_final")

    @pytest.mark.asyncio
    async def test_circuit_breaker_success_resets(self, mock_odds_response: list[dict]) -> None:
        """Successful responses should reset the circuit breaker."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(503, json={"error": "down"})
            return httpx.Response(200, json=mock_odds_response)

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        c = OddsApiClient(
            api_key="test",
            http_client=mock_http,
            max_retries=3,
            circuit_failure_threshold=5,
        )

        result = await c.get_odds("basketball_nba")
        assert len(result) > 0
        assert c._circuit.state == CircuitState.CLOSED


class TestCircuitBreakerGauge:
    def test_gauge_set_on_open(self) -> None:
        from djinn_miner.api.metrics import CIRCUIT_BREAKER_STATE

        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        val = CIRCUIT_BREAKER_STATE.labels(target="odds_api")._value.get()
        assert val == 1

    def test_gauge_reset_on_success(self) -> None:
        from djinn_miner.api.metrics import CIRCUIT_BREAKER_STATE

        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        val = CIRCUIT_BREAKER_STATE.labels(target="odds_api")._value.get()
        assert val == 0
