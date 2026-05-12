"""Audit-time recovery of missing Shamir shares from peer validators.

When the genius created a signal, the bundle was fanned out to every OV
signer (Phase 3, share recovery). Each validator decrypted its own entry
and persisted the rest as forwarding blobs. If THIS validator was 504-ing
during the original fan-out, we missed the bundle entirely and have no
share locally for that signal — but peers that DID receive the bundle hold
a forwarding ciphertext addressed to us.

This module fetches those forwarding blobs from peers and decrypts them
locally with our x25519 privkey, restoring the share in share_store before
the audit batch is built. See project_share_recovery_design_2026_05_03.md.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

from djinn_validator.utils.crypto import BN254_PRIME

# v1719: tightened recovery timeouts. Pre-fix, 5s read + 2s connect per
# peer × 5 peers × 10 signals = up to 250s per pair attempt for legacy
# pre-gossip-era pairs where every peer also lacks the data. Per-pair
# evict cycle was thus dominated by peer-recovery wait, not MPC. With
# 73 unsettleable legacy pairs in the queue, this kept UID 0 stuck on
# the head-of-queue for hours after the deterministic-sort fix.
# 2s read + 1s connect is enough for healthy peers (typical response
# < 100ms when they have the data, < 1s when they 404). Misses get
# retried later via reset_abstain on push gossip arrival (v1717).
_RECOVERY_TIMEOUT = httpx.Timeout(2.0, connect=1.0)


async def recover_missing_shares(
    *,
    signal_ids: list[str],
    share_store: Any,
    peer_validators: list[dict[str, Any]],
    encryption_privkey: bytes,
    signer_address: str,
    genius_address_for: dict[str, str] | None = None,
    shamir_threshold_default: int = 2,
) -> dict[str, int]:
    """Walk signal_ids; for each signal we don't have locally, pull a
    forwarding ciphertext from any peer that has one, decrypt with our
    x25519 privkey, and store via share_store.store(...).

    Args:
        signal_ids: signals to scan (typically the audit set's resolved set).
        share_store: ShareStore instance.
        peer_validators: list of {"url": ..., "uid": ...} entries; we fan
            out one HTTP GET per peer per missing signal until one
            returns 200. Iteration stops on first success per signal.
        encryption_privkey: 32-byte x25519 privkey for SealedBox decrypt.
        signer_address: this validator's signer EOA (lowercase or
            checksummed; we lowercase before posting in the path).
        genius_address_for: optional map signal_id -> genius_address;
            falls back to a placeholder zero-address when unknown
            because we'll still want the share recoverable for MPC even
            if we can't immediately resolve the genius (the genius
            stored on chain is authoritative; this metadata is local
            cache only).
        shamir_threshold_default: stored when peer doesn't return one.

    Returns a tally dict: keys are status codes ("recovered", "no_peer_had_it",
    "decrypt_failed", "store_failed", "skip_present"); values are counts.
    """
    if not signal_ids:
        return {}
    if not peer_validators:
        log.debug("share_recovery_no_peers", signal_count=len(signal_ids))
        return {}
    if len(encryption_privkey) != 32:
        log.warning("share_recovery_bad_privkey_len", got=len(encryption_privkey))
        return {}

    from djinn_validator.chain.encryption_keys import decrypt_sealed_box
    from djinn_validator.utils.crypto import Share

    target_addr = signer_address.lower()
    tally: dict[str, int] = {}

    # v1700: tick a Prometheus counter so /metrics surfaces the tally
    # fleet-wide. Uses safe_label_inc so a missing metrics module (e.g.
    # tests bypassing the registry) doesn't break recovery.
    from djinn_validator.api.metrics import (
        SHARE_RECOVERY_RESULT,
        safe_label_inc,
    )

    def bump(key: str) -> None:
        tally[key] = tally.get(key, 0) + 1
        safe_label_inc(SHARE_RECOVERY_RESULT, outcome=key)

    async with httpx.AsyncClient(timeout=_RECOVERY_TIMEOUT) as client:
        for signal_id in signal_ids:
            try:
                if share_store.has(signal_id):
                    bump("skip_present")
                    continue
            except Exception:
                pass

            recovered = False
            signal_skipped = False  # set when this signal hit skip_already_stored
            for peer in peer_validators:
                endpoint = f"{peer.get('url', '').rstrip('/')}/v1/share-recovery/{signal_id}/{target_addr}"
                try:
                    resp = await client.get(endpoint)
                except httpx.HTTPError as e:
                    # v1701: bump peer_unreachable so /metrics distinguishes
                    # network-error misses from 404 misses. Without this,
                    # network-flaky peers were silently rolled into
                    # no_peer_had_it, masking transport bugs as data gaps.
                    bump("peer_unreachable")
                    log.debug(
                        "share_recovery_http_error",
                        signal_id=signal_id[:20],
                        peer_uid=peer.get("uid"),
                        err=type(e).__name__,
                    )
                    continue
                if resp.status_code == 404:
                    # v1701: bump peer_404 so /metrics distinguishes
                    # peers that genuinely lack a forwarding entry from
                    # network-unreachable peers. Different remediation:
                    # 404 means the genius bundle never reached the peer
                    # (upstream replication gap); unreachable means we
                    # need to investigate routing or peer health.
                    bump("peer_404")
                    continue
                if resp.status_code != 200:
                    bump(f"peer_status_{resp.status_code}")
                    continue
                try:
                    body = resp.json()
                    share_x = int(body["share_x"])
                    share_ct_hex = body["share_ciphertext"]
                    index_ct_hex = body.get("index_ciphertext", "") or ""
                    threshold = int(body.get("shamir_threshold", shamir_threshold_default))
                except (KeyError, ValueError, TypeError) as e:
                    bump(f"bad_shape_{type(e).__name__}")
                    continue

                try:
                    share_ct = bytes.fromhex(share_ct_hex)
                    share_y_bytes = decrypt_sealed_box(encryption_privkey, share_ct)
                    index_y_bytes = b""
                    if index_ct_hex:
                        index_ct = bytes.fromhex(index_ct_hex)
                        index_y_bytes = decrypt_sealed_box(encryption_privkey, index_ct)
                except Exception as e:
                    bump(f"decrypt_failed_{type(e).__name__}")
                    log.warning(
                        "share_recovery_decrypt_failed",
                        signal_id=signal_id[:20],
                        peer_uid=peer.get("uid"),
                        err=str(e)[:100],
                    )
                    continue

                share_y = int.from_bytes(share_y_bytes, "big")
                if share_y < 0 or share_y >= BN254_PRIME:
                    bump("share_y_out_of_field")
                    continue

                genius_address = (genius_address_for or {}).get(signal_id, "0x0000000000000000000000000000000000000000")
                try:
                    share_store.store(
                        signal_id=signal_id,
                        genius_address=genius_address,
                        share=Share(x=share_x, y=share_y),
                        encrypted_key_share=share_y_bytes,
                        encrypted_index_share=index_y_bytes,
                        shamir_threshold=threshold,
                        precomputed_triples=[],
                    )
                except ValueError as e:
                    if "already stored" in str(e):
                        # Another path raced ahead; treat as recovered.
                        recovered = True
                        signal_skipped = True
                        bump("skip_already_stored")
                        break
                    bump(f"store_failed_{type(e).__name__}")
                    continue
                except Exception as e:
                    bump(f"store_failed_{type(e).__name__}")
                    log.warning(
                        "share_recovery_store_failed",
                        signal_id=signal_id[:20],
                        err=str(e)[:120],
                    )
                    continue

                bump("recovered")
                log.info(
                    "share_recovered_from_peer",
                    signal_id=signal_id[:20],
                    peer_uid=peer.get("uid"),
                )
                recovered = True
                break

            # v1701: per-signal flag replaces the old check
            # `tally.get("skip_already_stored", 0) == 0`. The old form
            # used the GLOBAL cumulative tally, so once any earlier
            # signal in this batch hit skip_already_stored, every
            # subsequent unrecovered signal silently failed to bump
            # no_peer_had_it. That hid real recovery gaps from /metrics.
            if not recovered and not signal_skipped:
                bump("no_peer_had_it")

    if tally:
        log.info("share_recovery_summary", **tally)
    return tally


async def gather_recovery(*coros) -> list[Any]:
    """Cheap wrapper for callers that want to fire several recover_missing_shares
    operations in parallel and collect tallies."""
    return await asyncio.gather(*coros, return_exceptions=False)
