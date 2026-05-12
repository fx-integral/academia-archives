# Outcome Layer Plan

**Goal:** game outcomes resolve identically across all validators, before any further work on audit settlement. P0-01 cannot close until this layer converges.

**Locked architecture:** see `~/.claude/projects/-home-user-djinn/memory/project_outcome_layer_design_2026_05_02.md`. Summary:

- Validators own ESPN. Miners own TLSN. Yuma slashes (TAO emissions). USDC bonds NOT used. Challenge window over bond+slash.
- Default path: each validator fetches ESPN, gossips resolved outcomes to peers, peers replay-verify by independent ESPN fetch.
- Escalation rungs: re-fetch (1) → byte-diff (2) → miner TLSN (3) → manual (4).

## Phase A: Outcome gossip + replay-verify

**Outcome:** when validator A resolves signal S, all peers also have S resolved within seconds (subject to ESPN replay-verify).

### A1: Gossip broadcast endpoint + sender
- New endpoint `POST /v1/outcomes/gossip` accepting `{signal_id, outcomes, raw_espn_summary, signer_uid}`. Auth via existing hotkey-signature middleware.
- New helper `_gossip_resolved_outcome_to_peers(neuron, signal_id, outcomes, raw)` modelled on `_gossip_purchase_odds_to_peers`. Fan out to all validator-permit peers, signed by hotkey, fire-and-forget, 5s timeout.
- After `OutcomeAttestor.resolve_all_pending` returns a resolved list, main loop fires one gossip per newly-resolved id.

### A2: Gossip receive + replay-verify
- New method `OutcomeAttestor.receive_gossip(signal_id, outcomes, raw_espn_summary, signer_hotkey)`:
  - Look up signal in `_pending_signals`. If absent: 404 (signal not registered yet locally — wait for purchase pipeline to register it).
  - If already resolved locally: 200 (idempotent).
  - Replay-verify: call own `fetch_event_result(meta.event_id, meta.sport, ...)`. If status not final/postponed/cancelled: log `outcome_gossip_pending_local`, defer.
  - Compare derived outcomes from local ESPN fetch to gossiped outcomes. If match: set `meta.resolved=True, meta.outcomes=outcomes`, call `audit_set_store.record_outcomes`, log `outcome_gossip_accepted`.
  - On mismatch: log `outcome_gossip_disputed` with both vectors, do NOT store. Queue for rung-3 escalation in Phase B.

### A3: Tests
- Unit: gossip payload serialization, signature verification, replay-verify match/mismatch decision.
- Integration: 2 mock validators sharing one ESPN client → A resolves, B receives gossip, B's `_pending_signals[S].resolved=True`.
- Adversarial: gossip with wrong outcomes → receiver's replay-verify catches it → `outcome_gossip_disputed` log, signal stays pending locally.

### A4: Ship
- Commit + tag `vNNNN` + push.
- Watchtower picks up on UID 0; verify via `pm2 logs djinn-validator | grep outcome_gossip`.
- Cross-check fleet convergence: `curl http://VALIDATOR/v1/audit/{g}/{i}/detail` per validator should show identical `resolved` purchase_id sets within 60s of any one validator resolving.

## Phase B: Dispute escalation via miners (rung 3)

When `outcome_gossip_disputed` fires for the same (signal_id, peer pair) more than N times in a window, escalate:
- Validator dispatches the corresponding ESPN URL through the existing `/v1/attest` miner pipeline (same primitive that handles `earthquake.usgs.gov` today).
- Miners produce TLSN proofs of ESPN's response.
- Validator verifies the proof, treats the proven outcome as canonical, overwrites local state if it disagreed.
- Validators score miners on attestation quality via existing Bittensor weight mechanism (Yuma feedback).

## Phase C: Audit contract upgrade (separate from outcome layer, queued for after C completes)

- New `Audit.submitOutcomeRoot(bytes32 root, bytes[] signatures)` accepting a Merkle root of canonical outcomes signed by stake-weighted validator majority.
- Challenge window (default 6h?) during which anyone can submit a contradicting TLSN proof to reverse a tentative outcome.
- After window: outcome is final, settlement uses it.

## Phase D: Hard testing

- `stress-scale --past-days=2 --count=30 --idiot-batch=10` against finished games (see `feedback_test_fixture_min_batch_gate.md` for why batch=10).
- Liveness test: stop UID 1's resolver, confirm gossip from peers fills in UID 1's resolved set.
- Adversarial test: inject wrong outcome on UID 0, confirm peer replay-verify catches it.
- ESPN throttle test: simulate 429 from ESPN, confirm validator backs off and gossip from peers covers the gap.

## Success criteria

Outcome layer is "done" when:
1. After `stress-scale --past-days=1 --count=30 --idiot-batch=10`, all 5 validators converge on identical `resolved` sets per (genius, idiot) pair within 5 minutes.
2. Adversarial outcome injection is caught and logged (no silent acceptance).
3. ESPN throttling on one validator is tolerated (peers fill in via gossip).
4. Validator restart picks up missed outcomes from peer gossip without re-fetching the entire ESPN window.

Only then proceed to audit settlement (rung-3 escalation, contract upgrade, etc.).
