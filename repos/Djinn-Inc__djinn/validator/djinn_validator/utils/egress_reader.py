"""Read all validator egress-IP commitments from the Bittensor chain.

Mirrors the miner-side reader (``djinn_miner.utils.egress_commitments``)
but runs on the validator and returns a per-UID map for the network
endpoints to surface. Cached because it's called per request from
``_build_metagraph_node`` and we'd otherwise issue ``n_validators``
chain RPCs on every public ``/v1/network/validators`` hit.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import structlog

from djinn_validator.utils.egress_publisher import parse_payload

log = structlog.get_logger()

_CACHE_TTL_S = 60.0
_cache: tuple[float, dict[int, list[str]]] | None = None
_cache_lock = threading.Lock()


def _read_uncached(neuron: Any) -> dict[int, list[str]]:
    if neuron is None or neuron.metagraph is None or neuron.subtensor is None:
        return {}
    if not hasattr(neuron.subtensor, "get_commitment"):
        return {}
    netuid = getattr(neuron, "netuid", None)
    if netuid is None:
        return {}

    out: dict[int, list[str]] = {}
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
            ips = parse_payload(raw)
            if ips:
                out[uid] = ips
    except Exception as e:
        log.warning("egress_reader_error", error=str(e))
    return out


def get_all_egress_commitments(neuron: Any) -> dict[int, list[str]]:
    """Return ``{uid: [ips]}`` for all validator-permit UIDs that have
    published a parseable egress-IP commitment. Cached for ``_CACHE_TTL_S``
    seconds since the network endpoints call this on every request.
    """
    global _cache
    now = time.monotonic()
    with _cache_lock:
        if _cache is not None and now - _cache[0] < _CACHE_TTL_S:
            return dict(_cache[1])
    fresh = _read_uncached(neuron)
    with _cache_lock:
        _cache = (now, fresh)
    return dict(fresh)


def reset_cache() -> None:
    """Test hook: clear the TTL cache."""
    global _cache
    with _cache_lock:
        _cache = None
