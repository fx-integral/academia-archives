"""One-off replay of local purchase_odds.db rows to committee peers.

Run this on a validator host (typically UID 0) after deploying v1433.
It reads every (signal_id, buyer_address, bpas, wpas, bpa_mode) tuple
from the local PurchaseOddsLedger and POSTs each to every *other*
validator in the committee via the new /v1/purchase_odds/record
endpoint — so shadow distributed settlement can assemble
PurchaseInputs on any peer, not just the purchase-handling validator
that originally recorded the row.

Idempotent: the endpoint is first-write-wins, so re-running this
script is safe. Peers that already have a given row return
duplicate=True.

Usage (on the validator host):
    cd /root/djinn/validator
    uv run python scripts/replay_purchase_odds_to_peers.py \\
        [--db /root/djinn/validator/data/purchase_odds.db]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402


def _load_rows(db_path: str) -> list[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT signal_id, buyer_address, bpa_mode, bpas_json, wpas_json FROM purchase_odds"
    )
    rows: list[dict[str, Any]] = []
    for r in cur:
        rows.append(
            {
                "signal_id": r["signal_id"],
                "buyer_address": r["buyer_address"],
                "bpa_mode": bool(r["bpa_mode"]),
                "bpas": json.loads(r["bpas_json"]),
                "wpas": json.loads(r["wpas_json"]),
            }
        )
    conn.close()
    return rows


def _load_peers(self_uid: int) -> list[dict[str, Any]]:
    """Read the metagraph and return peer validator URLs."""
    import bittensor as bt

    netuid = int(os.getenv("BT_NETUID", "103"))
    network = os.getenv("BT_NETWORK", "finney")
    # Newer bittensor exposes Subtensor (capital S); older exposes subtensor.
    Subtensor = getattr(bt, "Subtensor", None) or getattr(bt, "subtensor")
    subtensor = Subtensor(network=network)
    metagraph = subtensor.metagraph(netuid=netuid)

    from djinn_validator.core.mpc_orchestrator import _is_public_ip

    peers: list[dict[str, Any]] = []
    for uid in range(metagraph.n.item()):
        if not metagraph.validator_permit[uid].item():
            continue
        if uid == self_uid:
            continue
        axon = metagraph.axons[uid]
        if not axon.ip or axon.ip == "0.0.0.0":
            continue
        if not _is_public_ip(axon.ip):
            continue
        peers.append(
            {
                "uid": uid,
                "url": f"http://{axon.ip}:{axon.port}",
                "hotkey": metagraph.hotkeys[uid],
            }
        )
    return peers


def _load_wallet():
    import bittensor as bt

    Wallet = getattr(bt, "Wallet", None) or getattr(bt, "wallet")
    wallet = Wallet(
        name=os.getenv("BT_WALLET_NAME", "default"),
        hotkey=os.getenv("BT_WALLET_HOTKEY", "default"),
    )
    return wallet


async def _post_one(
    client: httpx.AsyncClient,
    peer: dict[str, Any],
    row: dict[str, Any],
    wallet: Any,
) -> tuple[str, int]:
    from djinn_validator.api.middleware import create_signed_headers

    body = json.dumps(row, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    headers.update(create_signed_headers("/v1/purchase_odds/record", body, wallet))
    try:
        r = await client.post(
            f"{peer['url']}/v1/purchase_odds/record",
            content=body,
            headers=headers,
            timeout=10.0,
        )
        return (f"uid={peer['uid']}", r.status_code)
    except httpx.HTTPError as e:
        return (f"uid={peer['uid']}", f"ERR {type(e).__name__}: {str(e)[:60]}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/root/djinn/validator/data/purchase_odds.db")
    parser.add_argument("--self-uid", type=int, default=int(os.getenv("DJINN_SELF_UID", "0")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = _load_rows(args.db)
    print(f"Loaded {len(rows)} rows from {args.db}")

    peers = _load_peers(args.self_uid)
    print(f"Discovered {len(peers)} committee peers: {[p['uid'] for p in peers]}")

    if args.dry_run:
        print("--dry-run: skipping POSTs")
        for row in rows:
            print(f"  would replay signal={row['signal_id'][:16]}... buyer={row['buyer_address'][:10]}")
        return

    wallet = _load_wallet()
    print(f"Loaded wallet hotkey={wallet.hotkey.ss58_address[:12]}...")

    totals: dict[str, int] = {"200_new": 0, "200_dup": 0, "other": 0, "errors": 0}
    async with httpx.AsyncClient() as client:
        for i, row in enumerate(rows):
            print(f"\n[{i+1}/{len(rows)}] signal={row['signal_id'][:20]}... buyer={row['buyer_address'][:10]}")
            results = await asyncio.gather(
                *(_post_one(client, p, row, wallet) for p in peers),
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, tuple):
                    peer_id, status = res
                    if status == 200:
                        # We don't read body here; approximate new vs dup later
                        totals["200_new"] += 1
                    elif isinstance(status, int):
                        totals["other"] += 1
                        print(f"  {peer_id}: HTTP {status}")
                    else:
                        totals["errors"] += 1
                        print(f"  {peer_id}: {status}")
                else:
                    totals["errors"] += 1
                    print(f"  exception: {res}")

    print(f"\n=== Totals: {totals}")


if __name__ == "__main__":
    asyncio.run(main())
