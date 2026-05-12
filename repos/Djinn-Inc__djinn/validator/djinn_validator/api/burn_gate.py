"""Burn-gate authentication for external notary session requests.

Callers prove they burned >= MIN_BURN_ALPHA of SN103 alpha within the last
BURN_WINDOW_SECONDS by providing:
  - X-Coldkey: their SS58 coldkey address (the extrinsic signer)
  - X-Signature: sr25519 signature of the burn tx hash (hex)
  - X-Burn-Tx: the extrinsic hash of the burn_alpha call

The caller stakes TAO on SN103 (to any validator), then calls burn_alpha
to permanently destroy alpha from that stake. The extrinsic is signed by
the coldkey. The validator verifies the signature, looks up the extrinsic
on-chain, and confirms the burn amount, recency, subnet, and coldkey match.

Results are cached so repeated requests with the same tx hash are instant.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import bittensor as bt
import structlog

log = structlog.get_logger()

BURN_CACHE_PATH = Path(
    os.getenv(
        "BURN_CACHE_PATH",
        os.path.expanduser("~/.local/share/djinn/burn_cache.json"),
    )
)

# Hardcoded constants (no .env override)
MIN_BURN_ALPHA: float = 1.0  # Minimum alpha burned per tx
BURN_WINDOW_SECONDS: int = 365 * 86400  # 1 year for initial on-chain verification
BURN_NETUID: int = 103
ALPHA_RAO_PER_TOKEN: int = 1_000_000_000  # 1 alpha = 1e9 rao

# Cache: tx_hash -> {valid, error, coldkey, amount, block_ts, checked_at}
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS: int = 300  # 5 minutes for invalid/not-found entries
# Once a burn is verified and cached, it stays valid permanently.
# The burn happened, the alpha is destroyed, re-verification is pointless.
# Block state gets pruned from subtensor nodes, so re-checking on-chain
# will fail for old burns even though they're perfectly valid.
CACHE_TTL_VALID_SECONDS: int = 10 * 365 * 86400  # 10 years (effectively permanent)


def _cache_ttl(entry: dict[str, Any]) -> int:
    """Valid burns are cached for the full burn window; failures expire fast."""
    return CACHE_TTL_VALID_SECONDS if entry.get("valid") else CACHE_TTL_SECONDS


def _load_cache() -> None:
    """Load persisted valid burn entries from disk on startup.

    Valid burns are loaded regardless of age. The burn happened, the
    alpha is destroyed. Re-verification would require on-chain lookup
    which fails when block state is pruned.
    """
    if not BURN_CACHE_PATH.exists():
        return
    try:
        data = json.loads(BURN_CACHE_PATH.read_text())
        loaded = 0
        for tx_hash, entry in data.items():
            if not entry.get("valid"):
                continue
            _cache[tx_hash] = entry
            loaded += 1
        if loaded:
            log.info("burn_cache_loaded", count=loaded)
    except Exception as e:
        log.warning("burn_cache_load_failed", error=str(e))


def _persist_cache() -> None:
    """Write valid burn entries to disk so they survive restarts."""
    valid_entries = {k: v for k, v in _cache.items() if v.get("valid")}
    if not valid_entries:
        return
    try:
        BURN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BURN_CACHE_PATH.write_text(json.dumps(valid_entries))
    except Exception as e:
        log.warning("burn_cache_persist_failed", error=str(e))


def _cache_get(tx_hash: str) -> dict[str, Any] | None:
    entry = _cache.get(tx_hash)
    if entry and (time.time() - entry["checked_at"]) < _cache_ttl(entry):
        return entry
    return None


def _cache_set(tx_hash: str, entry: dict[str, Any]) -> None:
    entry["checked_at"] = time.time()
    _cache[tx_hash] = entry
    # Evict old entries if cache grows too large
    if len(_cache) > 1000:
        now = time.time()
        stale = [k for k, v in _cache.items() if (now - v["checked_at"]) >= _cache_ttl(v)]
        for k in stale:
            del _cache[k]
    # Persist valid entries to disk
    if entry.get("valid"):
        _persist_cache()


# Load persisted burns on module import
_load_cache()


def verify_signature(coldkey_ss58: str, tx_hash_hex: str, signature_hex: str) -> bool:
    """Verify an sr25519 signature of the tx hash against the coldkey."""
    try:
        keypair = bt.Keypair(ss58_address=coldkey_ss58)
        tx_bytes = bytes.fromhex(tx_hash_hex.removeprefix("0x"))
        sig_bytes = bytes.fromhex(signature_hex.removeprefix("0x"))
        return keypair.verify(tx_bytes, sig_bytes)
    except Exception as e:
        log.warning("burn_gate_sig_verify_failed", coldkey=coldkey_ss58, error=str(e))
        return False


def verify_burn_tx(
    tx_hash: str,
    expected_coldkey: str,
    substrate: Any,
) -> tuple[bool, str]:
    """Look up a burn_alpha extrinsic on-chain and validate it.

    The extrinsic is signed by the coldkey. The hotkey param in the call
    identifies which validator's stake the alpha was burned from (the caller
    can stake to any validator on SN103, then burn from that position).

    Returns (valid, error_message).
    """
    # Check cache first.
    cached = _cache_get(tx_hash)
    if cached is not None:
        if not cached["valid"]:
            return False, cached["error"]
        if cached["coldkey"] != expected_coldkey:
            return False, "Burn coldkey does not match request coldkey"
        # Re-check age: a previously valid burn may have expired.
        block_ts = cached.get("block_ts", 0)
        if block_ts and (time.time() - block_ts) > BURN_WINDOW_SECONDS:
            age = int(time.time() - block_ts)
            expired_err = f"Burn too old ({age}s > {BURN_WINDOW_SECONDS}s)"
            _cache_set(
                tx_hash, {"valid": False, "error": expired_err, "coldkey": cached["coldkey"], "block_ts": block_ts}
            )
            return False, expired_err
        return True, ""

    tx_hash_clean = tx_hash.lower().removeprefix("0x")

    try:
        current_block = substrate.get_block_number(None)
        # 30 days at ~12s/block = ~216000 blocks; but the tx hash is provided
        # so we only need to scan far enough to find it. Use 7500 (~25h) as
        # initial scan depth; if the burn is older it will be cached from a
        # previous successful lookup.
        search_depth = 7500

        for block_num in range(current_block, max(current_block - search_depth, 0), -1):
            block_hash = substrate.get_block_hash(block_num)
            extrinsics = substrate.get_extrinsics(block_hash=block_hash)
            if not extrinsics:
                continue

            for ex in extrinsics:
                ex_hash = ex.extrinsic_hash
                if ex_hash is None:
                    continue
                if isinstance(ex_hash, bytes):
                    if ex_hash.hex() != tx_hash_clean:
                        continue
                elif isinstance(ex_hash, str):
                    if ex_hash.lower().removeprefix("0x") != tx_hash_clean:
                        continue
                else:
                    continue

                # Found the extrinsic
                call = ex.value.get("call", {})
                call_module = call.get("call_module", "")
                call_function = call.get("call_function", "")

                # Extract coldkey (extrinsic signer)
                coldkey = ""
                ex_address = ex.value.get("address", "")
                if isinstance(ex_address, str):
                    coldkey = ex_address
                elif isinstance(ex_address, dict):
                    coldkey = ex_address.get("Id", "")

                if call_module != "SubtensorModule" or call_function != "burn_alpha":
                    entry = {
                        "valid": False,
                        "error": f"Not a burn_alpha call ({call_module}.{call_function})",
                        "coldkey": coldkey,
                        "block_ts": 0,
                    }
                    _cache_set(tx_hash, entry)
                    return False, entry["error"]

                call_args = {a["name"]: a["value"] for a in call.get("call_args", [])}

                # Check netuid
                netuid = call_args.get("netuid", -1)
                if netuid != BURN_NETUID:
                    entry = {
                        "valid": False,
                        "error": f"Wrong subnet (netuid={netuid}, expected {BURN_NETUID})",
                        "coldkey": coldkey,
                        "block_ts": 0,
                    }
                    _cache_set(tx_hash, entry)
                    return False, entry["error"]

                # Check amount (in rao)
                amount_rao = call_args.get("amount", 0)
                amount_alpha = amount_rao / ALPHA_RAO_PER_TOKEN
                if amount_alpha < MIN_BURN_ALPHA:
                    entry = {
                        "valid": False,
                        "error": f"Burn amount {amount_alpha:.4f} alpha < {MIN_BURN_ALPHA} required",
                        "coldkey": coldkey,
                        "block_ts": 0,
                    }
                    _cache_set(tx_hash, entry)
                    return False, entry["error"]

                # Get block timestamp
                block_ts = 0
                block_data = substrate.get_block(block_hash)
                for bex in block_data.get("extrinsics", []):
                    bcall = bex.value.get("call", {})
                    if bcall.get("call_module") == "Timestamp":
                        ts_args = {a["name"]: a["value"] for a in bcall.get("call_args", [])}
                        block_ts = ts_args.get("now", 0) / 1000  # ms -> seconds
                        break

                # Check recency
                age = time.time() - block_ts
                if age > BURN_WINDOW_SECONDS:
                    entry = {
                        "valid": False,
                        "error": f"Burn too old ({int(age)}s > {BURN_WINDOW_SECONDS}s)",
                        "coldkey": coldkey,
                        "block_ts": block_ts,
                    }
                    _cache_set(tx_hash, entry)
                    return False, entry["error"]

                # Check coldkey matches
                if coldkey != expected_coldkey:
                    entry = {
                        "valid": False,
                        "error": "Burn coldkey does not match request coldkey",
                        "coldkey": coldkey,
                        "block_ts": block_ts,
                    }
                    _cache_set(tx_hash, entry)
                    return False, entry["error"]

                # All checks passed
                log.info(
                    "burn_verified",
                    tx_hash=tx_hash[:16] + "...",
                    coldkey=coldkey,
                    amount_alpha=amount_alpha,
                    block_num=block_num,
                )
                entry = {"valid": True, "error": "", "coldkey": coldkey, "amount": amount_alpha, "block_ts": block_ts}
                _cache_set(tx_hash, entry)
                return True, ""

        entry = {
            "valid": False,
            "error": f"Tx {tx_hash[:16]}... not found in last {search_depth} blocks",
            "coldkey": "",
            "block_ts": 0,
        }
        _cache_set(tx_hash, entry)
        return False, entry["error"]

    except Exception as e:
        log.warning("burn_gate_verify_error", tx_hash=tx_hash[:16], tx_hash_full=tx_hash, error=str(e))
        # Do NOT cache chain lookup failures (e.g. "State discarded").
        # The burn may be valid but unprovable right now. A peer validator
        # or a future archive node query could still verify it.
        return False, f"Chain lookup failed: {e}"


PEER_RESPONSE_MAX_AGE_S: int = 300  # max age of signed peer response


def _strict_recipient_enabled() -> bool:
    """Whether to reject legacy unbound peer responses (P1-25 hardening).

    Default off during the mixed-version rollout window so v1267+ callers
    can still form quorum with pre-v1267 peers. Once the network fully
    upgrades, operators flip `DJINN_BURN_GATE_STRICT_RECIPIENT=1` to close
    the cross-validator replay window entirely. Flagged by 2026-04-18
    fresh-eyes audit on v1267.
    """
    return os.getenv("DJINN_BURN_GATE_STRICT_RECIPIENT", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _record_fail_open(reason: str) -> None:
    """Bump the Prometheus fail-open counter; tolerate missing metrics module.

    Held-back HIGH from the 2026-04-18 v1273 fresh-eyes audit: the exception
    path in ``is_allowed_peer_ip`` logged but had no operator-visible rate
    signal. Without this, a silently-broken metagraph read would degrade the
    allowlist to pre-P1-26 behaviour with no alerting hook.
    """
    try:
        from djinn_validator.api.metrics import BURN_GATE_FAIL_OPEN

        BURN_GATE_FAIL_OPEN.labels(reason=reason).inc()
    except Exception:
        pass


def _normalize_ip(raw: str) -> str:
    """Canonicalize an IP for equality comparison.

    Strips IPv4-mapped IPv6 prefix (``::ffff:1.2.3.4`` → ``1.2.3.4``) so
    a peer reaching uvicorn over an IPv6 listener still matches an IPv4
    axon address in the metagraph. Returns the input unchanged when it
    isn't parseable so we never throw inside the allowlist check.
    """
    if not raw:
        return raw
    try:
        import ipaddress

        addr = ipaddress.ip_address(raw)
        mapped = getattr(addr, "ipv4_mapped", None)
        if mapped is not None:
            return str(mapped)
        return str(addr)
    except (ValueError, TypeError):
        return raw


def is_allowed_peer_ip(neuron: Any, request_ip: str) -> bool:
    """Whether the source IP is allowed to call `/v1/burn/verify` (P1-26).

    Policy: allow localhost (tests + self-probe), allow any IP that maps to
    a registered-validator axon in the metagraph, reject everything else.
    Escape hatch `DJINN_BURN_GATE_ALLOW_ANY_IP=1` restores pre-P1-26
    behavior (anonymous queries accepted) in case the allowlist misbehaves
    during mixed-version rollout.

    Fail-open when the metagraph is unavailable (neuron not yet wired,
    bittensor offline, or read failure) — the worst case is the pre-P1-26
    baseline that we already accept as shippable today. Once the metagraph
    loads, enforcement kicks in automatically.

    Per the P1-26 threat-model entry in MAINNET_BLOCKERS.md, this is
    defense-in-depth: impact is already gated by P1-24 cross-field quorum,
    but the unauthenticated query surface is the last free-amplification
    handle on the peer-quorum layer.

    Hardening after v1272 fresh-eyes audit (v1273, 2026-04-18):
      * Trust proxy-rewritten peer IP: uvicorn runs with
        ``proxy_headers=True`` in ``main.run_server``, so behind the
        wildcard nginx router ``request.client.host`` reflects the real
        remote address rather than ``127.0.0.1``.
      * Normalize IPv4-mapped IPv6 (``::ffff:a.b.c.d``) so dual-stack
        listeners still match IPv4 axon entries.
      * Reject the literal sentinel ``0.0.0.0`` in both the request and
        axon sides so unpublished-axon rows (common for offline peers)
        cannot match bogus requests.
    """
    if os.getenv("DJINN_BURN_GATE_ALLOW_ANY_IP", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return True

    request_ip = _normalize_ip(request_ip)

    if request_ip in ("127.0.0.1", "::1", "localhost"):
        return True

    # ``0.0.0.0`` is the unpublished-axon sentinel and should never match
    # an inbound request; reject early to avoid any accidental equality
    # with a pathologically-crafted or misconfigured request IP.
    if request_ip in ("0.0.0.0", ""):
        return False

    if neuron is None:
        _record_fail_open("neuron_missing")
        return True
    if getattr(neuron, "metagraph", None) is None:
        _record_fail_open("metagraph_missing")
        return True

    try:
        metagraph = neuron.metagraph
        n = metagraph.n.item() if hasattr(metagraph.n, "item") else int(metagraph.n)
        for uid in range(n):
            permit = metagraph.validator_permit[uid]
            is_validator = bool(permit.item() if hasattr(permit, "item") else permit)
            if not is_validator:
                continue
            axon = metagraph.axons[uid]
            axon_ip = _normalize_ip(getattr(axon, "ip", "") or "")
            if axon_ip in ("", "0.0.0.0"):
                continue
            if axon_ip == request_ip:
                return True
    except Exception as e:
        log.warning("burn_verify_allowlist_read_failed", error=str(e))
        _record_fail_open("metagraph_read_error")
        return True

    return False


def sign_peer_response(
    tx_hash: str,
    coldkey: str,
    valid: bool,
    amount: float,
    block_ts: float,
    signer_hotkey: str,
    wallet: Any,
    recipient_hotkey: str = "",
) -> dict[str, Any]:
    """Build a hotkey-signed peer response for /v1/burn/verify.

    Binds the response to (tx_hash, coldkey, valid, amount, block_ts,
    signer_hotkey, response_ts[, recipient_hotkey]). Recipient verifies the
    sr25519 signature against signer_hotkey and checks that signer_hotkey is
    a registered validator hotkey on the subnet metagraph. Same signing
    scheme as the validator's other inter-validator endpoints.

    When ``recipient_hotkey`` is provided (P1-25, 2026-04-18) it is folded
    into the signed payload so a response captured on the wire cannot be
    replayed to a different requesting validator. Empty string preserves
    the legacy payload shape for mixed-version rollout compatibility.
    """
    payload: dict[str, Any] = {
        "tx_hash": tx_hash,
        "coldkey": coldkey,
        "valid": valid,
        "amount": amount,
        "block_ts": block_ts,
        "signer_hotkey": signer_hotkey,
        "response_ts": int(time.time()),
    }
    if recipient_hotkey:
        payload["recipient_hotkey"] = recipient_hotkey
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    signature = wallet.hotkey.sign(payload_bytes).hex()
    return {**payload, "signature": signature}


def _verify_peer_response(
    data: dict[str, Any],
    expected_tx_hash: str,
    expected_coldkey: str,
    allowed_hotkeys: set[str],
    expected_recipient_hotkey: str = "",
) -> tuple[bool, str]:
    """Verify a signed peer response and its binding to the requested burn.

    Returns (ok, error). Rejects unsigned responses, bad signatures,
    responses from non-validator hotkeys, stale responses, or responses
    whose bound (tx_hash, coldkey) don't match the request.

    When ``expected_recipient_hotkey`` is provided AND the response contains
    a ``recipient_hotkey`` field, the two must match — this closes the
    cross-validator replay window (P1-25). Responses WITHOUT the field are
    still accepted during the mixed-version rollout. Once operators set
    ``DJINN_BURN_GATE_STRICT_RECIPIENT=1`` (see `_strict_recipient_enabled`),
    legacy unbound responses are rejected outright, closing the window
    entirely. Flagged by 2026-04-18 fresh-eyes audit on v1267.
    """
    signer = data.get("signer_hotkey")
    signature_hex = data.get("signature")
    if not signer or not signature_hex:
        return False, "unsigned peer response"

    if signer not in allowed_hotkeys:
        return False, f"signer {signer} not a registered validator"

    response_ts = data.get("response_ts", 0)
    age = time.time() - int(response_ts or 0)
    if age > PEER_RESPONSE_MAX_AGE_S or age < -PEER_RESPONSE_MAX_AGE_S:
        return False, f"stale or future-dated response (age={int(age)}s)"

    if data.get("tx_hash") != expected_tx_hash:
        return False, "tx_hash mismatch"
    if data.get("coldkey") != expected_coldkey:
        return False, "coldkey mismatch"

    response_recipient = data.get("recipient_hotkey")
    if expected_recipient_hotkey:
        if response_recipient is None:
            if _strict_recipient_enabled():
                return False, ("missing recipient_hotkey (strict mode rejects legacy " "unbound peer responses)")
            # else: legacy-rollout branch, fall through to accept
        elif response_recipient != expected_recipient_hotkey:
            return False, (
                f"recipient_hotkey mismatch "
                f"(response bound to {response_recipient}, "
                f"we are {expected_recipient_hotkey})"
            )

    payload = {
        "tx_hash": data["tx_hash"],
        "coldkey": data["coldkey"],
        "valid": bool(data.get("valid")),
        "amount": data.get("amount", 0),
        "block_ts": data.get("block_ts", 0),
        "signer_hotkey": data["signer_hotkey"],
        "response_ts": int(response_ts),
    }
    if response_recipient is not None:
        payload["recipient_hotkey"] = response_recipient
    payload_bytes = json.dumps(payload, sort_keys=True).encode()

    try:
        keypair = bt.Keypair(ss58_address=signer)
        if not keypair.verify(payload_bytes, bytes.fromhex(signature_hex)):
            return False, "invalid signature"
    except Exception as e:
        return False, f"signature verification error: {e}"

    return True, ""


async def verify_burn_via_peers(
    tx_hash: str,
    expected_coldkey: str,
    peer_urls: list[str],
    allowed_hotkeys: set[str] | None = None,
    self_hotkey: str = "",
) -> tuple[bool, str]:
    """Ask peer validators if they have a verified burn in their cache.

    Falls back to this when on-chain lookup fails (block state pruned).

    Each peer signs its response with its hotkey. We verify the signature
    against the signer hotkey and require the signer to be a registered
    validator on the metagraph. Quorum is by distinct signer hotkey so one
    peer can't double-count. If `allowed_hotkeys` is None the caller lacks
    metagraph context; we fail closed (return False) rather than trust
    unsigned/unauthenticated confirmations.

    ``self_hotkey`` (P1-25, 2026-04-18): the requesting validator's own
    hotkey. Sent as a query param and folded into each peer's signed
    payload so a captured response cannot be replayed to a different
    requester. Empty string (default) keeps the legacy behavior for the
    mixed-version rollout window.
    """
    if not peer_urls:
        return False, "No peer validators to query"

    if not allowed_hotkeys:
        log.warning(
            "burn_peer_verification_no_hotkey_set",
            tx_hash=tx_hash[:16] + "...",
            note="no metagraph hotkey set provided; rejecting all peer responses",
        )
        return False, "Peer verification unavailable (no metagraph context)"

    _PEER_QUORUM = 2  # minimum distinct-hotkey confirmations required
    # Cross-validate block_ts across signers. Real on-chain burn txs have a
    # single block_ts; peers should report the same value. Allow one Bittensor
    # block (~12s) of drift to absorb timestamp-capture skew. Disagreement
    # beyond this means at least one signer is reporting a false value (cache
    # poisoning attempt); refuse to form quorum rather than cache whichever
    # value arrived last.
    _BLOCK_TS_TOLERANCE_S: float = 12.0
    _AMOUNT_TOLERANCE: float = 1e-6  # float-drift tolerance; legitimate matches are exact

    import httpx

    confirming_hotkeys: set[str] = set()
    consensus_block_ts: float | None = None
    consensus_amount: float | None = None

    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in peer_urls:
            try:
                params: dict[str, str] = {
                    "tx_hash": tx_hash,
                    "coldkey": expected_coldkey,
                }
                if self_hotkey:
                    params["recipient_hotkey"] = self_hotkey
                resp = await client.get(
                    f"{url}/v1/burn/verify",
                    params=params,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not data.get("valid"):
                    continue
                ok, err = _verify_peer_response(
                    data,
                    tx_hash,
                    expected_coldkey,
                    allowed_hotkeys,
                    expected_recipient_hotkey=self_hotkey,
                )
                if not ok:
                    log.warning(
                        "burn_peer_response_rejected",
                        peer=url,
                        reason=err,
                        tx_hash=tx_hash[:16] + "...",
                    )
                    continue
                signer = data["signer_hotkey"]
                if signer in confirming_hotkeys:
                    continue  # same signer contributes at most once to quorum
                block_ts = float(data.get("block_ts", 0) or 0)
                amount = float(data.get("amount", 0) or 0)
                if consensus_block_ts is None:
                    consensus_block_ts = block_ts
                    consensus_amount = amount
                else:
                    if abs(block_ts - consensus_block_ts) > _BLOCK_TS_TOLERANCE_S:
                        log.warning(
                            "burn_peer_block_ts_mismatch",
                            peer=url,
                            signer=signer,
                            peer_block_ts=block_ts,
                            consensus_block_ts=consensus_block_ts,
                            tx_hash=tx_hash[:16] + "...",
                        )
                        continue
                    if abs(amount - (consensus_amount or 0.0)) > _AMOUNT_TOLERANCE:
                        log.warning(
                            "burn_peer_amount_mismatch",
                            peer=url,
                            signer=signer,
                            peer_amount=amount,
                            consensus_amount=consensus_amount,
                            tx_hash=tx_hash[:16] + "...",
                        )
                        continue
                confirming_hotkeys.add(signer)
                if len(confirming_hotkeys) >= _PEER_QUORUM:
                    log.info(
                        "burn_verified_via_peers",
                        tx_hash=tx_hash[:16] + "...",
                        hotkeys=sorted(confirming_hotkeys),
                        quorum=_PEER_QUORUM,
                        block_ts=consensus_block_ts,
                        amount=consensus_amount,
                    )
                    entry = {
                        "valid": True,
                        "error": "",
                        "coldkey": expected_coldkey,
                        "amount": consensus_amount or 0,
                        "block_ts": consensus_block_ts or 0,
                    }
                    _cache_set(tx_hash, entry)
                    _persist_cache()
                    return True, ""
            except Exception as e:
                log.debug("burn_peer_query_failed", peer=url, error=str(e))
                continue

    if confirming_hotkeys:
        return False, f"Only {len(confirming_hotkeys)} signed peer(s) confirmed (need {_PEER_QUORUM})"
    return False, "No peer validators could verify this burn with a valid signature"


def authenticate_request(
    coldkey_ss58: str,
    tx_hash_hex: str,
    signature_hex: str,
    substrate: Any,
    peer_validator_urls: list[str] | None = None,
) -> tuple[bool, str]:
    """Full burn-gate authentication: signature + on-chain verification.

    Returns (valid, error_message).
    """
    if not coldkey_ss58 or not tx_hash_hex or not signature_hex:
        return False, "Missing required headers: X-Coldkey, X-Burn-Tx, X-Signature"

    # Step 1: Verify the signature (fast, local)
    if not verify_signature(coldkey_ss58, tx_hash_hex, signature_hex):
        return False, "Invalid signature"

    # Step 2: Verify the burn on-chain (cached after first lookup)
    valid, error = verify_burn_tx(tx_hash_hex, coldkey_ss58, substrate)
    if valid:
        return True, ""

    # Step 3: On-chain lookup failed (likely pruned). Store the error and
    # peer_urls for the caller to try async peer verification.
    # We return the error context so the caller can decide.
    return False, error
