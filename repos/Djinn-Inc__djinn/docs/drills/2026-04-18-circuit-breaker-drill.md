# Circuit breaker staged-trip drill — 2026-04-18

**P1-10 · Circuit breaker never fired on live system** — first end-to-end
exercise of the CUSUM consensus circuit breaker and its `/v1/cb/appeal`
honor-system flow.

**Outcome:** PASS. A synthetic liar miner tripped the flag at sample
#118 of 500, persisted across a DB reopen, was queryable through
`/v1/cb/status/<hotkey>`, rejected a bogus appeal, accepted a
well-formed honor-system appeal, and reverted to `flagged=false,
score=0.0`. Drill wall time 0.83s; no Bittensor network calls.

## Why this drill exists

The CUSUM tracker landed in `djinn_validator/core/circuit_breaker.py`
behind `DJINN_FF_CIRCUIT_BREAKER`; the appeal endpoint landed at
`/v1/cb/appeal` behind `DJINN_FF_APPEAL_MECHANISM`. Both had unit
coverage (76 tests across four files) but nothing had ever exercised
the full flow against a running FastAPI server with persistence. P1-10
required a documented trip-and-appeal run before the mainnet gate
could close.

The drill also serves as a reproducible regression check: it can be
re-run any time the CUSUM constants, persistence layer, or appeal
endpoint changes, and its assertions will catch a broken wire
protocol before the flag fires in production.

## Environment

| Field | Value |
|---|---|
| Driver | `validator/scripts/circuit_breaker_drill.py` |
| Python | 3.12 (validator venv via `uv`) |
| Feature flags | `DJINN_FF_CIRCUIT_BREAKER=true`, `DJINN_FF_APPEAL_MECHANISM=true` |
| Network mode | `BT_NETWORK=test` (auth bypass for local drill) |
| Tracker params | tolerance=0.005, flag_threshold=5.0, decay=0.999 (production values) |
| Synthetic attacker | `5DrillTestSyntheticHotkey00…` (deviation=0.05 per observation) |
| Synthetic control | `5DrillTestOtherHotkey00…` (deviation=0.002 per observation) |
| Persistence | temp SQLite `/tmp/djinn-cb-drill-*/cusum.db` |

Auth enforcement for `/v1/cb/status` and `/v1/cb/appeal` is covered
separately in `tests/test_purchase_odds_endpoint_auth.py`; this drill
exercises the business logic in `BT_NETWORK=test` mode.

## Timeline

All times relative to drill start at `2026-04-18 19:49:15Z`.

| Phase | Step | Result |
|---|---|---|
| tracker | 500-observation loop at 0.05 deviation against synthetic hotkey | flagged at sample #118, score 5.011 |
| tracker | 30 observations at 0.002 deviation against control hotkey | score stayed 0.0 (below tolerance) |
| persistence | Close breaker, open fresh `ConsensusCircuitBreaker` on same DB | flagged state + 20 disputes restored |
| http | `GET /v1/cb/status/<synthetic>` | 200, `flagged=true, score=5.011, last_disputes=20` |
| http | `POST /v1/cb/appeal` with `disputed_query_ids=["nonexistent-1","nonexistent-2"]` | 200, `verdict=denied, cleared=false`; flag intact |
| http | `POST /v1/cb/appeal` with 3 of the 20 real disputed IDs | 200, `verdict=honor_system_accepted, cleared=true, new_score=0.0` |
| http | `GET /v1/cb/status/<synthetic>` after clear | 200, `flagged=false, score=0.0` |

## Raw drill output (excerpt)

```
[19:49:15Z] phase_tracker.start            db=/tmp/djinn-cb-drill-…/cusum.db
[19:49:15Z] phase_tracker.baseline         unflagged ✓
[warning] circuit_breaker_flagged hotkey=5DrillTest sample_count=118 score=5.011 threshold=5.0
[19:49:15Z] phase_tracker.flagged          tripped at sample #118, score=5.0110, disputes=20
[19:49:15Z] phase_tracker.decoy            honest miner score=0.000000 (stayed unflagged)
[19:49:15Z] phase_persistence.start        reopening DB
[info] circuit_breaker_loaded count=2
[19:49:15Z] phase_persistence.ok           flagged state survived, 20 disputes restored
[19:49:16Z] phase_http.status              GET /v1/cb/status/5DrillTestSy…
[info] request status=200 path=/v1/cb/status/… duration_ms=3.3
[19:49:16Z] phase_http.status.ok           flagged=true score=5.0110 disputes_returned=20
[19:49:16Z] phase_http.deny                POST /v1/cb/appeal with non-matching ids
[warning] cb_appeal_no_matching_disputes submitted=2 in_record=20
[19:49:16Z] phase_http.deny.ok             denied + still flagged ✓
[19:49:16Z] phase_http.appeal              POST /v1/cb/appeal with 3 real disputes
[info] circuit_breaker_flag_cleared hotkey=5DrillTest reason='appeal_honor_system matched=3 of 3' reset_score=True
[info] cb_appeal_accepted hotkey=5DrillTest matched=3 mode=honor_system
[19:49:16Z] phase_http.appeal.ok           honor_system_accepted + cleared ✓ score=0.0
[19:49:16Z] phase_http.post_clear.ok       flagged=false score=0.0 ✓
========================================================================
  DRILL PASS · 0.83s elapsed
========================================================================
```

## Detection dynamics

With the production parameters (tolerance=0.005, threshold=5.0,
decay=0.999) a miner lying at 0.05 per observation gets flagged in
~118 samples — roughly 20× faster than the ~1000-sample worst-case
discussed in `project_consensus_circuit_breaker.md` for a 0.01 liar.
That matches the design intent: bigger lies caught faster,
proportionally smaller damage before being caught.

Control observations at deviation=0.002 (below tolerance) contribute
zero to the score — the tracker correctly discards sub-tolerance
jitter so honest miners never drift toward the threshold from normal
upstream noise. This is the whole point of CUSUM over a naive
majority-vote disagreement counter.

## What the drill does NOT cover

1. **Real TLSNotary proof verification.** The appeal endpoint runs in
   honor-system mode (miner just has to know which query IDs are in
   their own dispute buffer). TLSNotary proof verification lands in a
   follow-up commit behind the same `DJINN_FF_APPEAL_MECHANISM` flag;
   the wire protocol was deliberately frozen now so the prover side
   could integrate.
2. **Hotkey-signed auth enforcement.** The drill runs with
   `BT_NETWORK=test` to skip auth. Production (`finney`/`mainnet`)
   enforces `validate_signed_request(request, {req.hotkey})` on
   `/v1/cb/appeal` and `{hotkey} ∪ validator_hotkeys` on
   `/v1/cb/status/<hotkey>`. That path is covered by
   `tests/test_purchase_odds_endpoint_auth.py`.
3. **Scoring-loop integration.** The drill tests the tracker and the
   appeal endpoint. The actual effect of a flag on forward weight
   emission (Yuma zero-out + slash economics) lives in
   `MinerScorer.compute_weights` and is covered by
   `test_circuit_breaker_scoring_integration.py`.
4. **Live validator on v0.djinn.gg.** Running the drill against a
   production validator would require a real signed request from a
   test hotkey registered on SN103. The standalone drill is the
   shippable equivalent: identical code paths, identical SQLite
   schema, identical FastAPI app, deterministic and fast. The
   next step, captured as P1-10 residual, is to reproduce this
   against UID 0 once we register a throwaway test hotkey.

## Unit-test corroboration

Running the three circuit-breaker test files alongside the drill:

```
uv run pytest tests/test_circuit_breaker.py tests/test_consensus_circuit_breaker.py \
                tests/test_cb_appeal_endpoint.py tests/test_circuit_breaker_scoring_integration.py -q
...
76 passed, 2 warnings in 5.12s
```

Both the drill and the pytest suite share the same
`ConsensusCircuitBreaker` and `/v1/cb/appeal` implementations, so a
regression in either will trip both checks.

## Follow-up work

- [ ] Register a dedicated test hotkey on SN103 and re-run the HTTP
  phase against UID 0 (`v0.djinn.gg`) in `finney` mode, exercising
  the auth-enforcement path end-to-end. Blocked on: assigning burn-free
  TAO for the test hotkey registration.
- [ ] Add a TLSNotary proof-verification mode to `/v1/cb/appeal` and
  extend the drill to submit an actual attested proof. Tracked
  separately in the appeal-mechanism follow-up.
- [ ] Wire this drill into CI so a regression in the appeal flow
  fails the build. Path: `.github/workflows/validator.yml` →
  `uv run python scripts/circuit_breaker_drill.py`.

## Artifacts

- Drill script: `validator/scripts/circuit_breaker_drill.py`
- Full drill log: captured inline above (also `/tmp/cb-drill.log`
  ephemeral).
- Unit tests: `validator/tests/test_{circuit_breaker,consensus_circuit_breaker,cb_appeal_endpoint,circuit_breaker_scoring_integration}.py`
- Design memo: `~/.claude/projects/-home-user-djinn/memory/project_consensus_circuit_breaker.md`
