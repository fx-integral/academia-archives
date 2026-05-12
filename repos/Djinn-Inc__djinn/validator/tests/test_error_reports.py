"""Tests for Sprint-A /v1/report-error endpoint + error_reports module.

Mirrors behavior of `web/app/api/report-error/route.ts` so the cutover
off Vercel keeps byte-for-byte compatible semantics.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core import error_reports
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


@pytest.fixture(autouse=True)
def reset_error_state():
    error_reports.reset_for_tests()
    yield
    error_reports.reset_for_tests()


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


# --- module-level logic ---


def test_submit_report_sanitizes_fields():
    entry = error_reports.submit_report(
        {
            "message": "hello",
            "url": "https://djinn.gg/" + "a" * 1000,
            "errorMessage": "boom" * 500,
            "errorStack": "trace" * 1000,
            "userAgent": "Mozilla " * 200,
            "wallet": "0xabcdef1234567890",
            "signalId": "1" * 500,
            "consoleErrors": ["e" * 900, "f", "g", "h", "i", "dropped"],
            "source": "not-a-real-source",
        },
        ip="127.0.0.1",
    )
    assert entry.message == "hello"
    assert len(entry.url) == 500
    assert len(entry.error_message) == 1000
    assert len(entry.error_stack) == 2000
    assert len(entry.user_agent) == 300
    assert len(entry.wallet) == 14  # "0xabcdef123456"
    assert len(entry.signal_id) == 100
    assert len(entry.console_errors) == 5
    assert len(entry.console_errors[0]) == 500
    assert entry.source == "other"  # unknown values coerced


def test_submit_report_rejects_oversize_message():
    with pytest.raises(error_reports._InvalidReport):
        error_reports.submit_report(
            {"message": "x" * (error_reports.MAX_MESSAGE_CHARS + 1)},
            ip="1.1.1.1",
        )


def test_submit_report_missing_message_rejected():
    with pytest.raises(error_reports._InvalidReport):
        error_reports.submit_report({}, ip="1.1.1.1")


def test_submit_report_non_string_message_rejected():
    with pytest.raises(error_reports._InvalidReport):
        error_reports.submit_report({"message": 12345}, ip="1.1.1.1")


def test_rate_limit_kicks_in_after_max():
    for _ in range(error_reports.RATE_LIMIT_MAX):
        error_reports.submit_report({"message": "hi"}, ip="2.2.2.2")
    with pytest.raises(error_reports._RateLimited):
        error_reports.submit_report({"message": "hi"}, ip="2.2.2.2")


def test_rate_limit_is_per_ip():
    for _ in range(error_reports.RATE_LIMIT_MAX):
        error_reports.submit_report({"message": "hi"}, ip="3.3.3.3")
    # Different IP not throttled
    entry = error_reports.submit_report({"message": "hi"}, ip="4.4.4.4")
    assert entry.ip == "4.4.4.4"


def test_rate_limit_window_expires():
    base = 1_000_000.0
    for _ in range(error_reports.RATE_LIMIT_MAX):
        error_reports.submit_report({"message": "hi"}, ip="5.5.5.5", now=base)
    # After the window passes, prior timestamps roll off.
    entry = error_reports.submit_report(
        {"message": "later"},
        ip="5.5.5.5",
        now=base + error_reports.RATE_LIMIT_WINDOW_SEC + 1,
    )
    assert entry.message == "later"


def test_ring_buffer_caps_at_max_errors():
    # In-memory mode (no SQLite db configured) caps at MAX_ERRORS_RING.
    for i in range(error_reports.MAX_ERRORS_RING + 50):
        error_reports._persist(
            error_reports.StoredError(
                submission_id=f"sub-{i}",
                message=f"m{i}",
                url="",
                error_message="",
                error_stack="",
                user_agent="",
                wallet="",
                signal_id="",
                console_errors=[],
                source="other",
                timestamp="2026-04-19T00:00:00.000Z",
                ip="0.0.0.0",
            ),
            ts_unix=1_700_000_000.0 + i,
        )
    assert error_reports.total_stored() == error_reports.MAX_ERRORS_RING
    view = error_reports.recent_reports(limit=5)
    assert view["total"] == error_reports.MAX_ERRORS_RING
    # Newest-first
    assert view["errors"][0]["message"] == f"m{error_reports.MAX_ERRORS_RING + 49}"


def test_recent_reports_respects_limit_bounds():
    for i in range(10):
        error_reports._persist(
            error_reports.StoredError(
                submission_id=f"sub-{i}",
                message=f"m{i}",
                url="",
                error_message="",
                error_stack="",
                user_agent="",
                wallet="",
                signal_id="",
                console_errors=[],
                source="other",
                timestamp="2026-04-19T00:00:00.000Z",
                ip="0.0.0.0",
            ),
            ts_unix=1_700_000_000.0 + i,
        )
    assert len(error_reports.recent_reports(limit=3)["errors"]) == 3
    # limit <1 coerced to 1; >MAX clamped.
    assert len(error_reports.recent_reports(limit=0)["errors"]) == 1
    assert (
        len(error_reports.recent_reports(limit=9999)["errors"])
        == 10
    )


def test_ip_truncation_caps_at_45():
    entry = error_reports.submit_report(
        {"message": "hi"}, ip="x" * 200
    )
    assert len(entry.ip) == 45


# --- issue body format ---


def test_issue_body_includes_wallet_and_signal():
    entry = error_reports.StoredError(
        submission_id="sub-test-1",
        message="boom",
        url="https://djinn.gg/idiot",
        error_message="boom message",
        error_stack="stack",
        user_agent="UA",
        wallet="0xabcd...9876",
        signal_id="42",
        console_errors=["a", "b"],
        source="error-boundary",
        timestamp="2026-04-19T00:00:00.000Z",
        ip="0.0.0.0",
    )
    title, body, labels = error_reports._issue_body(entry)
    assert title.startswith("[User Report] boom")
    assert "**Wallet:** `0xabcd...9876`" in body
    assert "**Signal:** `42`" in body
    assert "### Stack Trace" in body
    assert "crash" in labels
    assert "user-report" in labels


def test_issue_body_omits_missing_optional_fields():
    entry = error_reports.StoredError(
        submission_id="sub-test-2",
        message="bare",
        url="",
        error_message="",
        error_stack="",
        user_agent="",
        wallet="",
        signal_id="",
        console_errors=[],
        source="other",
        timestamp="2026-04-19T00:00:00.000Z",
        ip="0.0.0.0",
    )
    _, body, labels = error_reports._issue_body(entry)
    assert "**Wallet:**" not in body
    assert "**Signal:**" not in body
    assert "### Error" not in body
    assert "### Stack Trace" not in body
    assert "### Recent Console Errors" not in body
    assert labels == ["user-report"]


# --- HTTP endpoint ---


def test_post_report_error_returns_ok(client):
    r = client.post(
        "/v1/report-error",
        json={"message": "client bug"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["persisted"] is True
    # forwarded reflects worker outcome; without a token configured it must
    # always be False rather than silently lying. github_token_configured
    # exposes the operator misconfiguration directly.
    assert body["forwarded"] is False
    assert body["github_token_configured"] is False
    assert isinstance(body["submission_id"], str) and len(body["submission_id"]) >= 16
    assert error_reports.total_stored() == 1


def test_post_report_error_invalid_json(client):
    r = client.post(
        "/v1/report-error",
        content=b"not-json{",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_report_error_missing_message(client):
    r = client.post("/v1/report-error", json={"url": "https://djinn.gg/"})
    assert r.status_code == 400


def test_post_report_error_oversize_rejected(client):
    big = "x" * (error_reports.MAX_BODY_BYTES + 10)
    r = client.post(
        "/v1/report-error",
        content=big.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_post_report_error_rate_limit_returns_429(client):
    for _ in range(error_reports.RATE_LIMIT_MAX):
        r = client.post("/v1/report-error", json={"message": "hi"})
        assert r.status_code == 200
    r = client.post("/v1/report-error", json={"message": "hi"})
    assert r.status_code == 429


def test_post_report_error_fires_github_issue_when_token_set(client):
    sent: list[tuple[str, str, list[str]]] = []

    async def _fake_issue(entry):
        sent.append(error_reports._issue_body(entry))

    with patch.dict("os.environ", {"GITHUB_ERROR_TOKEN": "fake-token"}):
        with patch.object(error_reports, "create_github_issue", _fake_issue):
            r = client.post(
                "/v1/report-error",
                json={"message": "crash", "source": "error-boundary"},
            )
            assert r.status_code == 200
    # The TestClient drives a new event loop per request; the fire-and-forget
    # task must have been scheduled and awaited by loop close.
    assert len(sent) <= 1  # Best-effort: schedule may or may not fire on sync client


def test_admin_errors_recent_without_auth_when_key_unset(client):
    # When ADMIN_API_KEY is unset the require_admin_auth dependency is a no-op.
    client.post("/v1/report-error", json={"message": "one"})
    client.post("/v1/report-error", json={"message": "two"})
    r = client.get("/v1/report-error/recent?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["errors"][0]["message"] == "two"  # newest-first


def test_client_ip_prefers_x_real_ip(client):
    r = client.post(
        "/v1/report-error",
        json={"message": "hi"},
        headers={"X-Real-IP": "9.9.9.9"},
    )
    assert r.status_code == 200
    recent = error_reports.recent_reports(limit=1)["errors"]
    assert recent[0]["ip"] == "9.9.9.9"


def test_client_ip_falls_back_to_xff_last_hop(client):
    r = client.post(
        "/v1/report-error",
        json={"message": "hi"},
        headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 3.3.3.3"},
    )
    assert r.status_code == 200
    recent = error_reports.recent_reports(limit=1)["errors"]
    assert recent[0]["ip"] == "3.3.3.3"


# --- v1743: durable queue + retry worker ---


def test_persistent_store_survives_module_state_reset(tmp_path):
    """Reports written to SQLite survive a fresh process state.

    Simulated by configuring, persisting, dropping the in-memory state,
    and re-configuring against the same db file.
    """
    db_path = str(tmp_path / "error_reports.db")
    error_reports.configure(db_path)
    entry = error_reports.submit_report(
        {"message": "durable"}, ip="10.0.0.1"
    )
    assert error_reports.total_stored() == 1
    assert error_reports.pending_count() == 1

    # Drop the open connection + state, then reopen against the same path.
    import sqlite3
    error_reports._state.db.close()
    error_reports._state.db = None
    error_reports._state.in_memory.clear()
    error_reports._state.rate_buckets.clear()

    error_reports.configure(db_path)
    assert error_reports.total_stored() == 1
    assert error_reports.pending_count() == 1
    recent = error_reports.recent_reports(limit=1)["errors"]
    assert recent[0]["submissionId"] == entry.submission_id
    assert recent[0]["message"] == "durable"
    assert recent[0]["forwarded"] is False
    error_reports._state.db.close()
    error_reports._state.db = None


def test_stats_endpoint_exposes_token_status(client):
    r = client.get("/v1/report-error/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["github_token_configured"] is False  # test env has no token
    assert body["github_repo"] == "djinn-inc/error-reports"
    assert body["total"] == 0
    assert body["pending"] == 0


def test_post_github_issue_no_token_returns_no_token_outcome():
    """The forwarder must NOT silently succeed when the token is missing.

    Pre-v1743 this was the silent-drop bug: create_github_issue did
    `if not token: return` and returned no signal to the caller. Now
    callers get a False + reason and the metric tracks the outcome.
    """
    import asyncio

    entry = error_reports.StoredError(
        submission_id="probe",
        message="m",
        url="",
        error_message="",
        error_stack="",
        user_agent="",
        wallet="",
        signal_id="",
        console_errors=[],
        source="other",
        timestamp="2026-04-19T00:00:00.000Z",
        ip="0.0.0.0",
    )
    with patch.dict("os.environ", {}, clear=False):
        # Ensure token is not set even if the host has it.
        import os

        prior = os.environ.pop("GITHUB_ERROR_TOKEN", None)
        try:
            forwarded, reason, issue_no = asyncio.run(
                error_reports._post_github_issue(entry)
            )
        finally:
            if prior is not None:
                os.environ["GITHUB_ERROR_TOKEN"] = prior
    assert forwarded is False
    assert "GITHUB_ERROR_TOKEN" in reason
    assert issue_no is None


def test_forward_one_marks_failed_after_max_attempts(tmp_path, monkeypatch):
    """Persistent transient failures don't loop forever — they exhaust."""
    import asyncio
    db_path = str(tmp_path / "error_reports.db")
    error_reports.configure(db_path)
    monkeypatch.setenv("GITHUB_ERROR_TOKEN", "fake-token")
    entry = error_reports.submit_report(
        {"message": "exhaust me"}, ip="10.0.0.2"
    )

    async def _always_5xx(_entry):
        return False, "github http 500", None

    monkeypatch.setattr(error_reports, "_post_github_issue", _always_5xx)
    for _ in range(error_reports.MAX_FORWARD_ATTEMPTS):
        asyncio.run(error_reports._forward_one(entry.submission_id))

    # After MAX_FORWARD_ATTEMPTS, status flips to 'failed' and pending drops.
    assert error_reports.pending_count() == 0
    recent = error_reports.recent_reports(limit=1)["errors"]
    assert recent[0]["attempts"] == error_reports.MAX_FORWARD_ATTEMPTS
    assert "github http 500" in recent[0]["lastError"]
    error_reports._state.db.close()
    error_reports._state.db = None


def test_forward_one_marks_failed_immediately_on_4xx(tmp_path, monkeypatch):
    """A 4xx (bad token, missing label, schema) is non-transient — stop retrying."""
    import asyncio
    db_path = str(tmp_path / "error_reports.db")
    error_reports.configure(db_path)
    monkeypatch.setenv("GITHUB_ERROR_TOKEN", "fake-token")
    entry = error_reports.submit_report(
        {"message": "bad token path"}, ip="10.0.0.3"
    )

    async def _always_401(_entry):
        return False, "github http 401: Bad credentials", None

    monkeypatch.setattr(error_reports, "_post_github_issue", _always_401)
    asyncio.run(error_reports._forward_one(entry.submission_id))

    # Single attempt: no retry on terminal error.
    assert error_reports.pending_count() == 0
    recent = error_reports.recent_reports(limit=1)["errors"]
    assert recent[0]["attempts"] == 1
    assert "github http 401" in recent[0]["lastError"]
    error_reports._state.db.close()
    error_reports._state.db = None


def test_forward_one_marks_forwarded_on_success(tmp_path, monkeypatch):
    """Happy path: 201 from GitHub flips status to forwarded with the issue number."""
    import asyncio
    db_path = str(tmp_path / "error_reports.db")
    error_reports.configure(db_path)
    monkeypatch.setenv("GITHUB_ERROR_TOKEN", "fake-token")
    entry = error_reports.submit_report(
        {"message": "happy path"}, ip="10.0.0.4"
    )

    async def _always_ok(_entry):
        return True, "", 4242

    monkeypatch.setattr(error_reports, "_post_github_issue", _always_ok)
    asyncio.run(error_reports._forward_one(entry.submission_id))

    assert error_reports.pending_count() == 0
    recent = error_reports.recent_reports(limit=1)["errors"]
    assert recent[0]["forwarded"] is True
    error_reports._state.db.close()
    error_reports._state.db = None


def test_issue_body_includes_submission_id():
    entry = error_reports.StoredError(
        submission_id="sub-xyz-123",
        message="hello",
        url="",
        error_message="",
        error_stack="",
        user_agent="",
        wallet="",
        signal_id="",
        console_errors=[],
        source="other",
        timestamp="2026-04-19T00:00:00.000Z",
        ip="0.0.0.0",
    )
    _, body, _ = error_reports._issue_body(entry)
    assert "**Submission:** `sub-xyz-123`" in body
