"""Pull-side recovery for outcome gossip.

Mirrors share-recovery Phase 5: when a validator missed a peer's push of a
resolved outcome (HTTP down, rate-limited 429, restart, etc.) and is now
about to assemble an audit batch, it scans audit_set_store for purchases
whose outcomes haven't been recorded locally and pulls them from peers
via GET /v1/outcomes/{signal_id}. The receiver replay-verifies via
independent ESPN fetch, exactly like the push-gossip path; peer's
response is treated as a hint, never as authority.

See project_outcome_recovery_design_2026_05_03.md.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_RECOVERY_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


async def recover_missing_outcomes(
    *,
    signal_ids: list[str],
    peer_validators: list[dict[str, Any]],
    outcome_attestor: Any,
    audit_set_store: Any | None = None,
) -> dict[str, int]:
    """For each signal_id whose outcome is unresolved locally, fan-out a
    GET to each peer's /v1/outcomes/{signal} until one responds 200 with
    resolved outcomes.

    The peer returns metadata (event_id, sport, teams, lines) plus the
    resolved outcomes. We:
      1. If signal not registered locally yet: register the metadata.
      2. Call outcome_attestor.receive_gossip(...) to apply the same
         replay-verify-against-ESPN that the push-gossip path runs.
      3. On accept: outcomes are stored; main loop's audit pipeline
         picks them up on the next scan.

    Returns a tally dict for telemetry: keys are status counts (recovered,
    no_peer_had_it, replay_disputed, replay_pending_local, registration_failed,
    skip_already_resolved, peer_4xx_<status>, exc_<class>).
    """
    if not signal_ids or not peer_validators or outcome_attestor is None:
        return {}

    tally: dict[str, int] = {}

    def bump(key: str) -> None:
        tally[key] = tally.get(key, 0) + 1

    # v1703: bounded-cardinality Prometheus counter mirrors local tally
    # so /metrics surfaces fleet-wide. Best-effort import; missing
    # metrics module (tests) doesn't break recovery.
    def _tick(outcome: str) -> None:
        try:
            from djinn_validator.api.metrics import OUTCOME_RECOVERY_RESULT

            OUTCOME_RECOVERY_RESULT.labels(outcome=outcome).inc()
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=_RECOVERY_TIMEOUT) as client:
        for signal_id in signal_ids:
            local = outcome_attestor.get_signal(signal_id)
            if local is not None and local.resolved:
                bump("skip_already_resolved")
                _tick("skip_already_resolved")
                continue

            recovered = False
            for peer in peer_validators:
                url = peer.get("url", "").rstrip("/")
                if not url:
                    continue
                endpoint = f"{url}/v1/outcomes/{signal_id}"
                try:
                    resp = await client.get(endpoint)
                except httpx.HTTPError as e:
                    bump(f"exc_{type(e).__name__}")
                    _tick("peer_unreachable")
                    continue

                if resp.status_code == 404:
                    _tick("peer_404")
                    continue
                if resp.status_code != 200:
                    bump(f"peer_status_{resp.status_code}")
                    if 400 <= resp.status_code < 500:
                        _tick("peer_status_4xx")
                    elif 500 <= resp.status_code < 600:
                        _tick("peer_status_5xx")
                    else:
                        _tick("peer_status_other")
                    continue

                try:
                    body = resp.json()
                except Exception as e:
                    bump(f"bad_json_{type(e).__name__}")
                    _tick("bad_json")
                    continue

                if not body.get("resolved") or not body.get("outcomes"):
                    # Peer has metadata but no resolved outcomes — try next.
                    continue

                # Register signal locally if we don't have its metadata.
                # We use the peer-supplied metadata only as the FRAME for
                # replay-verify; the outcomes themselves go through ESPN.
                if local is None:
                    try:
                        import time as _time

                        from djinn_validator.core.outcomes import (
                            SignalMetadata,
                            parse_pick,
                        )

                        lines_raw = body.get("lines") or []
                        if not isinstance(lines_raw, list) or not lines_raw:
                            bump("registration_failed_no_lines")
                            _tick("registration_failed")
                            continue
                        # Each line is a JSON-serialized ParsedPick string.
                        # parse_pick accepts both the v2 JSON form and the
                        # v1 human-readable form.
                        parsed = []
                        for s in lines_raw:
                            if not isinstance(s, str) or not s.strip():
                                continue
                            try:
                                parsed.append(parse_pick(s))
                            except (TypeError, ValueError):
                                continue
                        if len(parsed) == 0:
                            bump("registration_failed_no_lines")
                            _tick("registration_failed")
                            continue

                        meta = SignalMetadata(
                            signal_id=signal_id,
                            sport=body.get("sport", ""),
                            event_id=body.get("event_id", ""),
                            home_team=body.get("home_team", ""),
                            away_team=body.get("away_team", ""),
                            lines=parsed,
                            purchased_at=_time.time(),
                        )
                        # v1724: outcome-recovery from peer is a trusted
                        # internal path (peer is hotkey-authenticated upstream);
                        # allow overwrite of stale local metadata.
                        outcome_attestor.register_signal(meta, allow_overwrite=True)
                        local = meta
                    except Exception as e:
                        bump(f"registration_failed_{type(e).__name__}")
                        _tick("registration_failed")
                        continue

                # Replay-verify via the existing gossip path. Peer's hotkey
                # is unknown to us in pull mode (we didn't authenticate the
                # response); use a placeholder. receive_gossip uses
                # signer_hotkey for logging only.
                try:
                    status, _ = await outcome_attestor.receive_gossip(
                        signal_id=signal_id,
                        gossiped_outcomes=[int(o) for o in body["outcomes"]],
                        signer_hotkey=peer.get("hotkey", "pull-recovery"),
                    )
                except Exception as e:
                    bump(f"receive_gossip_exc_{type(e).__name__}")
                    _tick("receive_gossip_err")
                    continue

                if status == "accepted":
                    bump("recovered")
                    _tick("recovered")
                    recovered = True
                    log.info(
                        "outcome_recovered_from_peer",
                        signal_id=signal_id[:20],
                        peer_uid=peer.get("uid"),
                    )
                    break
                if status == "already_resolved":
                    bump("skip_already_resolved")
                    _tick("skip_already_resolved")
                    recovered = True
                    break
                if status == "disputed":
                    # Peer's outcomes mismatched our independent ESPN fetch.
                    # Try next peer; first one to match ESPN wins.
                    bump("replay_disputed")
                    _tick("replay_disputed")
                    continue
                if status == "pending_local":
                    # Our own ESPN says game not final yet. No peer can
                    # convince us otherwise in this pass; abandon for now.
                    bump("replay_pending_local")
                    _tick("replay_pending_local")
                    break
                if status == "unknown_signal":
                    # Registration above didn't take effect; should not
                    # happen unless there's a race. Try next peer.
                    bump("unknown_signal_after_register")
                    _tick("unknown_signal_after_register")
                    continue
                bump(f"unexpected_status_{status}")
                _tick("receive_gossip_err")  # bucket unexpected statuses here

            if not recovered:
                bump("no_peer_had_it")
                _tick("no_peer_had_it")

    if tally:
        log.info("outcome_recovery_summary", **tally)
    return tally
