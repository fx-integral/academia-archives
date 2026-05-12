"""Read validator egress-IP commitments from the Bittensor metagraph.

Validators publish a comma-separated list of IPs from which they make
outbound TLS connections (e.g. NAT egress, secondary NIC, proxy). The
miner unions these with the metagraph axon IPs so validators behind
NAT can reach the API even when their inbound source IP differs from
the axon IP they advertise on-chain.

Format on chain: ``"1.2.3.4,5.6.7.8"`` (plain ASCII, comma-separated).
A leading ``{`` is treated as an unrelated commitment (e.g. tunnel
shield JSON) and ignored.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from typing import Any

import structlog

log = structlog.get_logger()

MAX_IPS_PER_VALIDATOR = 5
# Middleware calls the read path on every protected request; the chain
# RPC is far too expensive for that hot path. Cache the union for 60s.
_CACHE_TTL_S = 60.0
_cache: tuple[float, set[str]] | None = None
_cache_lock = threading.Lock()


def _is_routable(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_private or addr.is_link_local:
        return False
    if addr.is_multicast or addr.is_unspecified or addr.is_reserved:
        return False
    return True


def parse_egress_ips(raw: Any, max_ips: int = MAX_IPS_PER_VALIDATOR) -> set[str]:
    """Parse a commitment payload into a set of routable IPs.

    Returns an empty set on any parse failure or if the payload looks
    like JSON (so we don't collide with the tunnel-shield commitment
    format used by miners).
    """
    if raw is None:
        return set()
    if isinstance(raw, bytes):
        try:
            text = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return set()
    else:
        text = str(raw)
    text = text.strip()
    if not text or text.startswith("{") or text.startswith("["):
        return set()

    ips: set[str] = set()
    for part in text.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        if not _is_routable(candidate):
            continue
        ips.add(candidate)
        if len(ips) >= max_ips:
            break
    return ips


def _read_uncached(neuron: Any) -> set[str]:
    if neuron is None or neuron.metagraph is None or neuron.subtensor is None:
        return set()
    if not hasattr(neuron.subtensor, "get_commitment"):
        return set()
    netuid = getattr(neuron, "netuid", None)
    if netuid is None:
        return set()

    out: set[str] = set()
    try:
        n = neuron.metagraph.n
        if hasattr(n, "item"):
            n = n.item()
        for uid in range(int(n)):
            permit = neuron.metagraph.validator_permit[uid]
            if hasattr(permit, "item"):
                permit = permit.item()
            if not permit:
                continue
            try:
                raw = neuron.subtensor.get_commitment(netuid, uid)
            except Exception:
                continue
            if not raw:
                continue
            out.update(parse_egress_ips(raw))
    except Exception as e:
        log.warning("egress_commitments_read_error", error=str(e))
    return out


def get_validator_egress_ips(neuron: Any) -> set[str]:
    """Read egress-IP commitments for all validator-permit UIDs.

    Cached for ``_CACHE_TTL_S`` seconds because the auth middleware
    calls this on every protected request. Falls back silently on any
    RPC error so the axon-IP allowlist still works.
    """
    global _cache
    now = time.monotonic()
    with _cache_lock:
        if _cache is not None and now - _cache[0] < _CACHE_TTL_S:
            return set(_cache[1])
    fresh = _read_uncached(neuron)
    with _cache_lock:
        _cache = (now, fresh)
    return set(fresh)


def reset_cache() -> None:
    """Test hook: clear the TTL cache."""
    global _cache
    with _cache_lock:
        _cache = None
