"""Read-only subgraph client for audit_bootstrap fast path.

The Graph indexes every Escrow.purchaseV2 event into a Purchase entity
with the (genius, idiot, signal_id, purchase_id, notional, slaMultiplierBps)
tuple audit_bootstrap needs. One GraphQL query per pair replaces ~3-5 RPC
calls per purchase × N purchases per pair × M pairs — fleet-wide
convergence time drops from minutes (per-validator RPC pagination
cadence varies) to "as fast as subgraph indexing" (typically 1-2 blocks).

Fail-open by design: if the subgraph is stale (>150 blocks behind chain),
errors, or is unreachable, callers fall back to chain RPC. The subgraph
is treated as a cache, never as authority. Settlement correctness still
rests on the on-chain root.

See project_open_backlog_2026_04_16.md ("subgraph swap pending operator
redeploy"). Subgraph deployment lives at
https://api.studio.thegraph.com/query/1742249/djinn/v2.5.2 (confirmed
fresh on 2026-05-04).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

log = structlog.get_logger()


_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
# Subgraph block lag tolerance. ~150 blocks ≈ 5 min on Base Sepolia
# (2s blocks). If the subgraph trails chain by more than this, fall
# back to RPC to avoid voting on stale state.
_DEFAULT_MAX_LAG_BLOCKS = int(os.getenv("DJINN_SUBGRAPH_MAX_LAG_BLOCKS", "150"))


class SubgraphClient:
    """Minimal HTTP client for The Graph hosted subgraph queries."""

    def __init__(self, url: str, max_lag_blocks: int = _DEFAULT_MAX_LAG_BLOCKS) -> None:
        self.url = url
        self.max_lag_blocks = max_lag_blocks

    async def get_meta(self) -> dict[str, Any] | None:
        """Return the subgraph's `_meta` block: { block { number, timestamp } }.
        Returns None on transport / parse error.
        """
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(
                    self.url,
                    json={"query": "{ _meta { block { number timestamp } hasIndexingErrors } }"},
                )
                if resp.status_code != 200:
                    return None
                body = resp.json()
                meta = body.get("data", {}).get("_meta")
                if not meta:
                    return None
                return meta
        except (httpx.HTTPError, ValueError, KeyError) as e:
            log.debug("subgraph_meta_failed", err=str(e)[:120])
            return None

    async def is_fresh(self, chain_latest_block: int) -> bool:
        """True iff subgraph latest indexed block >= chain - max_lag_blocks."""
        meta = await self.get_meta()
        if meta is None:
            return False
        try:
            indexed = int(meta["block"]["number"])
        except (KeyError, ValueError, TypeError):
            return False
        if meta.get("hasIndexingErrors"):
            log.warning("subgraph_indexing_errors", indexed=indexed)
            return False
        lag = chain_latest_block - indexed
        return lag <= self.max_lag_blocks

    async def get_pair_purchases(self, genius: str, idiot: str) -> list[dict[str, Any]] | None:
        """Return all Pending Purchase entities for a (genius, idiot) pair.

        Returns:
          list of dicts with keys:
            purchase_id (int), signal_id (str), notional (int),
            sla_bps (int)
          ordered by onChainPurchaseId ascending. Empty list if pair has
          no pending purchases.
          None if the subgraph errors or returns malformed data — caller
          falls back to RPC scan.

        The subgraph entity uses lowercase address ids; we normalize the
        inputs to lowercase before querying.
        """
        query = """
        query($genius: String!, $idiot: String!) {
            purchases(
                where: { genius: $genius, idiot: $idiot, outcome: Pending }
                first: 1000
                orderBy: onChainPurchaseId
                orderDirection: asc
            ) {
                onChainPurchaseId
                notional
                signal { id slaMultiplierBps }
            }
        }
        """
        variables = {
            "genius": genius.lower(),
            "idiot": idiot.lower(),
        }
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(
                    self.url,
                    json={"query": query, "variables": variables},
                )
                if resp.status_code != 200:
                    log.warning("subgraph_query_status", status=resp.status_code)
                    return None
                body = resp.json()
                if "errors" in body:
                    log.warning("subgraph_query_errors", errors=str(body["errors"])[:200])
                    return None
                rows = body.get("data", {}).get("purchases", [])
        except (httpx.HTTPError, ValueError) as e:
            log.warning("subgraph_query_transport", err=str(e)[:120])
            return None

        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                signal = r.get("signal") or {}
                out.append(
                    {
                        "purchase_id": int(r["onChainPurchaseId"]),
                        "signal_id": str(signal["id"]),
                        "notional": int(r["notional"]),
                        "sla_bps": int(signal.get("slaMultiplierBps", 10_000)),
                    }
                )
            except (KeyError, ValueError, TypeError) as e:
                log.warning(
                    "subgraph_row_bad_shape",
                    err=str(e)[:80],
                    row=str(r)[:200],
                )
                # One bad row doesn't poison the rest; fall through.
                continue
        return out


# Hardcoded default points to the canonical Graph Studio deployment for
# Djinn on Base Sepolia. Operators who don't set DJINN_SUBGRAPH_URL get
# the fast path automatically — no per-operator config needed for the
# steady-state benefit. Override via env when running against a private
# subgraph mirror or a future versioned endpoint. Set DJINN_SUBGRAPH_URL=""
# (empty string) to opt out entirely and force RPC-only behavior.
_DEFAULT_SUBGRAPH_URL = "https://api.studio.thegraph.com/query/1742249/djinn/v2.5.2"


def get_default_subgraph_client() -> SubgraphClient | None:
    """Construct a client from DJINN_SUBGRAPH_URL or fall back to the
    hardcoded canonical Graph Studio deployment. Returns None only if
    the operator explicitly set DJINN_SUBGRAPH_URL="" to opt out.
    """
    raw = os.getenv("DJINN_SUBGRAPH_URL")
    if raw is None:
        # Env unset → use hardcoded default. Most operators land here.
        return SubgraphClient(url=_DEFAULT_SUBGRAPH_URL)
    url = raw.strip()
    if not url:
        # Explicit empty string → operator opt-out.
        return None
    return SubgraphClient(url=url)
