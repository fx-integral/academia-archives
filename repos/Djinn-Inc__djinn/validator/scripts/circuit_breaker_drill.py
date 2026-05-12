"""Circuit breaker staged-trip drill.

Runs the full CUSUM flag -> status -> appeal -> clear flow end-to-end
with a synthetic hotkey, then tears down. Safe to run against a
validator DB that has no real data since it uses a fresh temp sqlite
path; safe to run standalone since it spawns its own FastAPI test
client.

Exits non-zero on any assertion failure so it can be wired into CI.

Usage:
    cd /home/user/djinn/validator
    uv run python scripts/circuit_breaker_drill.py

This is the autonomous half of MAINNET_BLOCKERS.md P1-10:

    staged trip on testnet with synthetic bad-data scenario; verify
    appeals process works end-to-end.

It covers:

  1. Tracker primitive: 200 observations at deviation=0.05 flag the miner.
  2. Persistence: re-opening the DB restores the flagged state.
  3. HTTP wire: GET /v1/cb/status/<hotkey> returns flagged=true with
     the recorded dispute list.
  4. HTTP wire: POST /v1/cb/appeal with a matching dispute clears the
     flag in honor-system mode.
  5. Status after clear: flag=false, score=0.
  6. Denial path: POST /v1/cb/appeal with non-matching disputes leaves
     the flag in place.

The drill uses BT_NETWORK=test + DJINN_FF_APPEAL_MECHANISM=true to
exercise the business logic path. The auth-enforcement path is
covered separately in tests/test_purchase_odds_endpoint_auth.py.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import time
from pathlib import Path

# Ensure the validator package resolves when this script is run from
# anywhere. Works both via `uv run` (sys.path already correct) and via
# a raw python invocation from the repo root.
HERE = Path(__file__).resolve().parent
VALIDATOR_ROOT = HERE.parent
if str(VALIDATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_ROOT))


SYNTHETIC_HOTKEY = "5DrillTestSyntheticHotkey00000000000000000000000000"
DECOY_HOTKEY = "5DrillTestOtherHotkey0000000000000000000000000000000"


def log(step: str, msg: str = "") -> None:
    ts = time.strftime("%H:%M:%S", time.gmtime())
    print(f"[{ts}Z] {step:<30s} {msg}")


def phase_tracker(db_path: str) -> dict:
    from djinn_validator.core.circuit_breaker import ConsensusCircuitBreaker

    log("phase_tracker.start", f"db={db_path}")
    cb = ConsensusCircuitBreaker(
        tolerance=0.005,
        flag_threshold=5.0,
        decay_per_observation=0.999,
        db_path=db_path,
    )

    assert not cb.is_flagged(SYNTHETIC_HOTKEY), "fresh hotkey must start unflagged"
    log("phase_tracker.baseline", "unflagged ✓")

    tripped_at = None
    for i in range(500):
        cb.record_observation(
            hotkey=SYNTHETIC_HOTKEY,
            deviation=0.05,
            query_id=f"drill-q{i}",
        )
        if cb.is_flagged(SYNTHETIC_HOTKEY) and tripped_at is None:
            tripped_at = i + 1
            break

    assert tripped_at is not None, "expected flag within 500 obs at 0.05 deviation"
    state = cb.get_state(SYNTHETIC_HOTKEY)
    log(
        "phase_tracker.flagged",
        f"tripped at sample #{tripped_at}, score={state.score:.4f}, disputes={len(state.last_disputes)}",
    )

    for i in range(30):
        cb.record_observation(
            hotkey=DECOY_HOTKEY,
            deviation=0.002,
            query_id=f"decoy-q{i}",
        )
    assert not cb.is_flagged(DECOY_HOTKEY), "honest (<tolerance) miner must stay unflagged"
    log("phase_tracker.decoy", f"honest miner score={cb.get_score(DECOY_HOTKEY):.6f} (stayed unflagged)")

    return {
        "tripped_at": tripped_at,
        "score": state.score,
        "sample_count": state.sample_count,
        "disputes": [qid for qid, _ in state.last_disputes],
    }


def phase_persistence(db_path: str) -> None:
    """Close the breaker, reopen from the same DB, confirm the flag persists."""
    from djinn_validator.core.circuit_breaker import ConsensusCircuitBreaker

    log("phase_persistence.start", "reopening DB")
    cb2 = ConsensusCircuitBreaker(
        tolerance=0.005,
        flag_threshold=5.0,
        decay_per_observation=0.999,
        db_path=db_path,
    )
    assert cb2.is_flagged(SYNTHETIC_HOTKEY), "flag must survive restart"
    state = cb2.get_state(SYNTHETIC_HOTKEY)
    assert state is not None and len(state.last_disputes) > 0, "disputes must persist"
    log("phase_persistence.ok", f"flagged state survived, {len(state.last_disputes)} disputes restored")


def phase_http(db_path: str, disputes_from_tracker: list[str]) -> None:
    """Exercise the /v1/cb/status and /v1/cb/appeal endpoints.

    Spawns a private FastAPI TestClient against a newly-constructed
    app with a fresh ConsensusCircuitBreaker sharing the tracker's
    SQLite state. BT_NETWORK=test skips auth; DJINN_FF_APPEAL_MECHANISM
    is toggled on so /v1/cb/appeal doesn't 503.
    """
    os.environ["BT_NETWORK"] = "test"
    os.environ["DJINN_FF_APPEAL_MECHANISM"] = "true"
    os.environ["DJINN_FF_CIRCUIT_BREAKER"] = "true"

    from djinn_validator import feature_flags

    importlib.reload(feature_flags)

    from djinn_validator.api.server import create_app
    from djinn_validator.core.circuit_breaker import ConsensusCircuitBreaker
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.core.purchase import PurchaseOrchestrator
    from djinn_validator.core.outcomes import OutcomeAttestor
    from djinn_validator.core.scoring import MinerScorer
    from fastapi.testclient import TestClient

    cb = ConsensusCircuitBreaker(
        tolerance=0.005,
        flag_threshold=5.0,
        decay_per_observation=0.999,
        db_path=db_path,
    )
    share_store = ShareStore()
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor(espn_client=None)
    scorer = MinerScorer(circuit_breaker=cb)

    app = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
        scorer=scorer,
    )
    client = TestClient(app)

    log("phase_http.status", f"GET /v1/cb/status/{SYNTHETIC_HOTKEY[:12]}…")
    resp = client.get(f"/v1/cb/status/{SYNTHETIC_HOTKEY}")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["flagged"] is True, f"expected flagged=true, got {body}"
    assert body["sample_count"] >= 1, body
    assert body["score"] >= 5.0, body
    recorded_ids = [row[0] for row in body["last_disputes"]]
    assert len(recorded_ids) > 0, "status endpoint must return last_disputes for appeal construction"
    log("phase_http.status.ok", f"flagged=true score={body['score']:.4f} disputes_returned={len(recorded_ids)}")

    log("phase_http.deny", "POST /v1/cb/appeal with non-matching ids")
    resp = client.post(
        "/v1/cb/appeal",
        json={
            "hotkey": SYNTHETIC_HOTKEY,
            "declared_source": "https://drill.djinn.gg/fake-source",
            "disputed_query_ids": ["nonexistent-1", "nonexistent-2"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "denied", body
    assert body["cleared"] is False, body
    assert cb.is_flagged(SYNTHETIC_HOTKEY), "denial path must NOT clear the flag"
    log("phase_http.deny.ok", "denied + still flagged ✓")

    log("phase_http.appeal", f"POST /v1/cb/appeal with {len(recorded_ids[:3])} real disputes")
    resp = client.post(
        "/v1/cb/appeal",
        json={
            "hotkey": SYNTHETIC_HOTKEY,
            "declared_source": "https://drill.djinn.gg/source",
            "disputed_query_ids": recorded_ids[:3],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "honor_system_accepted", body
    assert body["cleared"] is True, body
    assert body["new_score"] == 0.0, body
    assert body["verification_mode"] == "honor_system", body
    assert not cb.is_flagged(SYNTHETIC_HOTKEY), "appeal must clear the flag"
    log("phase_http.appeal.ok", "honor_system_accepted + cleared ✓ score=0.0")

    log("phase_http.post_clear", f"GET /v1/cb/status/{SYNTHETIC_HOTKEY[:12]}… after clear")
    resp = client.get(f"/v1/cb/status/{SYNTHETIC_HOTKEY}")
    body = resp.json()
    assert body["flagged"] is False, body
    assert body["score"] == 0.0, body
    log("phase_http.post_clear.ok", "flagged=false score=0.0 ✓")


def main() -> int:
    start = time.time()
    print("=" * 72)
    print("  Circuit breaker staged-trip drill (P1-10)")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}")
    print(f"  Synthetic hotkey: {SYNTHETIC_HOTKEY}")
    print("=" * 72)

    with tempfile.TemporaryDirectory(prefix="djinn-cb-drill-") as tmp:
        db_path = str(Path(tmp) / "cusum.db")
        try:
            tracker_result = phase_tracker(db_path)
            phase_persistence(db_path)
            phase_http(db_path, tracker_result["disputes"])
        except AssertionError as e:
            print(f"\nFAIL: {e}")
            return 1
        except Exception as e:
            print(f"\nERROR: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
            return 2

    elapsed = time.time() - start
    print("=" * 72)
    print(f"  DRILL PASS · {elapsed:.2f}s elapsed")
    print(f"  Tripped at sample #{tracker_result['tripped_at']} " f"(score {tracker_result['score']:.4f})")
    print("  Status endpoint returns flagged state + last_disputes ✓")
    print("  Appeal with matching disputes clears flag (honor-system) ✓")
    print("  Appeal with non-matching disputes is denied ✓")
    print("  Persistence across reopen ✓")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
