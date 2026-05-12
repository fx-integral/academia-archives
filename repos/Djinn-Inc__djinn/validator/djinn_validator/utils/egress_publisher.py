"""Publish this validator's outbound IPs as a Bittensor on-chain commitment.

Validators behind NAT, multi-NIC VPS, or egress proxies emit TLS traffic
from a different IP than the axon they advertise on the metagraph.
Miner firewalls (and validator-auth middleware) whitelist the axon IP
only, so those validators get refused.

By default we auto-detect this validator's outbound IP via a public
reflector (api.ipify.org, ifconfig.me, icanhazip.com — first parseable
wins) and publish it to the per-subnet commitment slot. Operators with
multiple egress IPs (load balancer pool, dual-NIC) override via the
``DJINN_VALIDATOR_EGRESS_IPS`` env (comma-separated, up to 5).

Idempotent: only writes when the on-chain payload differs. Bittensor
rate-limits commitment writes per tempo; spurious rewrites silently
fail until the next window.
"""

from __future__ import annotations

import ipaddress
import os
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

ENV_VAR = "DJINN_VALIDATOR_EGRESS_IPS"
ENV_MAX_VAR = "DJINN_VALIDATOR_EGRESS_IP_MAX"
# Hard ceiling. Each IP is one more place that can call protected miner
# endpoints, so the cap is small by default and can only go down via env.
HARD_MAX_IPS = 5
DEFAULT_MAX_IPS = 1


def get_max_ips() -> int:
    """Operator-tunable cap on commitment entries.

    ``DJINN_VALIDATOR_EGRESS_IP_MAX`` (default 1) clamps to ``[0,
    HARD_MAX_IPS]``. ``0`` disables the publisher entirely (no chain
    write, no auto-detect). ``1`` is the common single-egress case.
    Raise toward 5 only if you genuinely have multiple outbound IPs
    (load balancer pool, multi-NIC) — every extra entry is one more
    permitted source on every miner's firewall.
    """
    raw = os.getenv(ENV_MAX_VAR, "").strip()
    if not raw:
        return DEFAULT_MAX_IPS
    try:
        n = int(raw)
    except ValueError:
        log.warning("egress_max_invalid", value=raw, fallback=DEFAULT_MAX_IPS)
        return DEFAULT_MAX_IPS
    return max(0, min(HARD_MAX_IPS, n))


# Back-compat alias for tests / external imports that referenced the
# old constant. Reflects the hard ceiling, not the runtime cap.
MAX_IPS = HARD_MAX_IPS
REFLECTORS = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)
REFLECTOR_TIMEOUT_S = 5.0
# Set by detect_egress_ip(); read by /health for the operator diagnostic.
_self_detected_ip: str | None = None


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


def _normalize(raw: str | None) -> list[str]:
    """Parse a string into a deduped, validated IP list (capped, in input order).

    Insertion order is preserved so the auto-detect FIFO can drop the
    oldest entry on overflow without losing idempotency on the next
    write (the chain payload uses the same order). Cap honours
    ``get_max_ips()``.
    """
    if not raw:
        return []
    cap = get_max_ips()
    if cap == 0:
        return []
    seen: dict[str, None] = {}  # dict-as-ordered-set
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate or candidate in seen:
            continue
        if not _is_routable(candidate):
            log.warning("egress_ip_rejected", ip=candidate, reason="not routable")
            continue
        seen[candidate] = None
        if len(seen) >= cap:
            break
    return list(seen.keys())


def _decode(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        try:
            return raw.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError:
            return ""
    return str(raw).strip()


def detect_egress_ip(force: bool = False) -> str | None:
    """Probe public reflectors for this host's outbound IPv4.

    First call hits the network; subsequent calls return the cached value.
    Pass ``force=True`` (the periodic loop does this) to re-probe — egress
    IPs can rotate over the life of a process (NAT pool refresh, ISP
    failover, multi-NIC rebalance).
    """
    global _self_detected_ip
    if _self_detected_ip is not None and not force:
        return _self_detected_ip
    for url in REFLECTORS:
        try:
            resp = httpx.get(url, timeout=REFLECTOR_TIMEOUT_S)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        candidate = resp.text.strip()
        if _is_routable(candidate):
            _self_detected_ip = candidate
            log.info("egress_ip_detected", ip=candidate, source=url)
            return candidate
    log.warning("egress_ip_detection_failed", reflectors=list(REFLECTORS))
    return None


def get_self_detected_ip() -> str | None:
    """Return the cached self-detected egress IP without probing."""
    return _self_detected_ip


def _reset_detection() -> None:
    """Test hook: clear the cached self-detected IP."""
    global _self_detected_ip
    _self_detected_ip = None


def parse_payload(raw: Any) -> list[str]:
    """Parse a chain commitment into a sorted list of routable IPs.

    Returns an empty list on any parse failure or if the payload looks
    like JSON (so we don't collide with the tunnel-shield commitment
    format used by miners). Public so the reader path can reuse the
    same validation as the publisher.
    """
    text = _decode(raw)
    if not text or text.startswith("{") or text.startswith("["):
        return []
    return _normalize(text)


def _own_axon_ip(neuron: Any) -> str:
    """Return this validator's own metagraph axon IP, or '' if unavailable."""
    try:
        uid = neuron.uid
        axon = neuron.metagraph.axons[uid]
        ip = getattr(axon, "ip", "") or ""
        return ip if ip and ip != "0.0.0.0" else ""
    except Exception:
        return ""


def _compute_desired(neuron: Any) -> tuple[list[str], str]:
    """Decide what should be on chain right now.

    - Cap is 0: disabled, return [] (publisher will short-circuit).
    - Env set: env wins outright (operator override). No FIFO accumulation.
    - Env empty + detected == own axon IP: skip — the miner's axon-IP
      allowlist already covers this validator, the commitment would be
      pure overhead.
    - Otherwise: auto-detect, then FIFO-merge with whatever's already on
      chain. New IP gets appended; if we'd exceed the cap, the oldest
      entry is dropped. Lets a validator that rotates outbound IPs over
      time accumulate up to ``cap`` recent ones rather than thrashing.
    """
    cap = get_max_ips()
    if cap == 0:
        return [], "disabled"

    env_ips = _normalize(os.getenv(ENV_VAR))
    if env_ips:
        return env_ips, "env"

    detected = detect_egress_ip(force=True)
    if not detected:
        return [], "none"

    if detected == _own_axon_ip(neuron):
        return [], "axon-match"

    current = _read_current_chain_list(neuron)
    if detected in current and len(current) <= cap:
        return current, "auto-detect"

    new_list = [ip for ip in current if ip != detected] + [detected]
    if len(new_list) > cap:
        new_list = new_list[-cap:]
    return new_list, "auto-detect"


def _read_current_chain_list(neuron: Any) -> list[str]:
    """Read the current commitment from chain and parse it back to a list.

    Returns an empty list on any read/parse failure so the FIFO can
    initialize from scratch.
    """
    if neuron is None or neuron.subtensor is None:
        return []
    if not hasattr(neuron.subtensor, "get_commitment"):
        return []
    netuid = getattr(neuron, "netuid", None)
    uid = getattr(neuron, "uid", None)
    if netuid is None or uid is None:
        return []
    try:
        raw = neuron.subtensor.get_commitment(netuid, uid)
    except Exception:
        return []
    return parse_payload(raw)


def publish_egress_ips(neuron: Any) -> bool:
    """One-shot: compute desired list and write to chain if it differs.

    Returns True on a successful write, False if no write was needed or
    the SDK/wallet/subtensor isn't ready. Never raises — egress hints are
    a soft signal and a missing commitment just falls back to axon-IP
    whitelisting (the existing behaviour). Called once at startup AND on
    each epoch tick so the FIFO can accumulate new outbound IPs over time.
    """
    desired, source = _compute_desired(neuron)
    if not desired:
        if source == "axon-match":
            log.info("egress_publish_skipped", reason="detected IP equals own axon IP")
        return False

    if neuron is None or neuron.subtensor is None or neuron.wallet is None:
        log.info("egress_publish_skipped", reason="neuron not ready")
        return False
    if not hasattr(neuron.subtensor, "set_commitment"):
        log.warning("egress_publish_skipped", reason="bittensor SDK lacks set_commitment")
        return False

    netuid = getattr(neuron, "netuid", None)
    uid = getattr(neuron, "uid", None)
    if netuid is None or uid is None:
        log.info("egress_publish_skipped", reason="uid/netuid not set")
        return False

    payload = ",".join(desired)

    try:
        current_raw = neuron.subtensor.get_commitment(netuid, uid)
        current = _decode(current_raw)
    except Exception as e:
        log.warning("egress_get_commitment_failed", error=str(e))
        current = ""

    if current == payload:
        log.info("egress_commitment_in_sync", ips=desired, source=source)
        return False

    try:
        neuron.subtensor.set_commitment(
            wallet=neuron.wallet,
            netuid=netuid,
            data=payload,
        )
        log.info("egress_commitment_published", ips=desired, bytes=len(payload), source=source)
        return True
    except Exception as e:
        log.warning("egress_commitment_write_failed", error=str(e), payload=payload)
        return False


# SN103 tempo is 360 blocks ≈ 72min; commitment writes are rate-limited
# per tempo so don't poll faster than this.
EPOCH_INTERVAL_S = 72 * 60


async def egress_publish_loop(neuron: Any) -> None:
    """Background task: re-publish egress commitment every epoch.

    Runs once immediately, then sleeps EPOCH_INTERVAL_S between iterations.
    Re-detects the outbound IP each time and FIFO-merges any new value
    into the chain commitment (auto-detect mode only). With env override
    set, becomes a noop after the first sync.
    """
    import asyncio

    while True:
        try:
            publish_egress_ips(neuron)
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("egress_publish_loop_error", error=str(e))
        try:
            await asyncio.sleep(EPOCH_INTERVAL_S)
        except asyncio.CancelledError:
            return
