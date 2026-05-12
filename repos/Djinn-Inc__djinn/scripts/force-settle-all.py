#!/usr/bin/env python3
"""scripts/force-settle-all.py

Owner-only routine settlement: discover every (g, i) pair with pending
purchases on Account, compute the on-chain qualityScore via
Audit.computeScore(), then schedule + execute Audit.forceSettle for
each.

This is the brutal-pragmatic alternative to multi-validator MPC quorum.
The deployer reads on-chain state directly and writes settlement
results, sidestepping Layer-2 batchKey divergence. The 2026-05-03 drill
(tx 0x6a2d25fe...e6016ca) proved the path works for a single batch;
this script does it for every pair.

Trade-off: centralized at the owner. Acceptable on Base Sepolia testnet
while the multi-validator quorum protocol is stabilized. The contract
path stays unchanged (forceSettle was already an owner-only emergency
route); we're just running it routinely.

Discovery + score computation use direct JSON-RPC (httpx). Submission
shells out to `forge` because we need the deployer's private key. Run
from a box with foundry installed.

Usage
-----
DRY_RUN=1 ./scripts/force-settle-all.py            # discover + report only
DEPLOYER_KEY=0x... ./scripts/force-settle-all.py   # submit each pair

Environment
-----------
DEPLOYER_KEY        Owner private key (only required for submit; foundry uses)
BASE_RPC_URL        default https://sepolia.base.org
DRY_RUN             1 → print only, no submit
SKIP_OUTCOMES       1 → skip the per-purchase outcome check; use score=0
                    (mirrors the 2026-05-03 drill)
PAIR_FILTER         genius:0x... or idiot:0x... to limit
PER_PAIR_DELAY_S    default 80 (72s timelock + buffer)
FROM_BLOCK          default LATEST-100000 (~14 days back on Base)

Exit codes
----------
0   success
1   fatal (RPC failure, missing forge for submit)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from typing import Any

import httpx

ACCOUNT = "0x4546354Dd32a613B76Abf530F81c8359e7cE440B"
AUDIT = "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E"
TIMELOCK = "0x37f41EFfa8492022afF48B9Ef725008963F14f79"

# keccak256 of event signature + function selectors.
# Verified via:
#   python3 -c "from Crypto.Hash import keccak; k=keccak.new(digest_bits=256); k.update(b'PurchaseRecorded(address,address,uint256,uint256)'); print(k.hexdigest())"
PURCHASE_RECORDED_TOPIC = (
    "0xca3eb5e06868f11093c340b698679a10f0d2ae66af994a368fb5cb489bcfd94c"
)
SEL_GET_PAIR_PURCHASE_IDS = "0x1a00b293"  # getPairPurchaseIds(address,address)
SEL_COMPUTE_SCORE = "0xf9adf6d2"          # computeScore(address,address,uint256[])
SEL_IS_PURCHASE_AUDITED = "0xfd2b01c6"    # isPurchaseAudited(uint256)


def rpc(method: str, params: list[Any], rpc_url: str, retries: int = 3) -> Any:
    """JSON-RPC with retry on transient failures (sepolia.base.org 502s a lot)."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = httpx.post(rpc_url, json=body, timeout=30.0)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"{method}: {data['error']}")
            return data["result"]
        except (httpx.HTTPError, RuntimeError) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def encode_address(addr: str) -> str:
    """Pad address to 32 bytes for ABI encoding."""
    return addr.lower().replace("0x", "").rjust(64, "0")


def encode_uint256(n: int) -> str:
    return f"{n:064x}"


def hex_to_int(h: str) -> int:
    return int(h, 16)


def get_logs(rpc_url: str, address: str, topic0: str, from_block: int, to_block: int) -> list[dict]:
    """Page through eth_getLogs in 5k-block chunks (most public RPCs cap there)."""
    out = []
    chunk = 4500
    cur = from_block
    while cur <= to_block:
        end = min(cur + chunk, to_block)
        params = [
            {
                "fromBlock": hex(cur),
                "toBlock": hex(end),
                "address": address,
                "topics": [topic0],
            }
        ]
        try:
            logs = rpc("eth_getLogs", params, rpc_url)
            out.extend(logs)
        except RuntimeError as e:
            # If RPC complains about range, halve and retry once.
            print(f"  [warn] getLogs {cur}..{end} failed: {e}", file=sys.stderr)
        cur = end + 1
    return out


def discover_pairs(rpc_url: str, from_block: int, to_block: int) -> list[tuple[str, str]]:
    print(
        f"scanning PurchaseRecorded on Account ({ACCOUNT}), blocks {from_block}..{to_block}",
        file=sys.stderr,
    )
    logs = get_logs(rpc_url, ACCOUNT, PURCHASE_RECORDED_TOPIC, from_block, to_block)
    print(f"  retrieved {len(logs)} PurchaseRecorded events", file=sys.stderr)

    pairs: set[tuple[str, str]] = set()
    for entry in logs:
        topics = entry.get("topics") or []
        if len(topics) < 3:
            continue
        # topics[1] = genius (32B), topics[2] = idiot (32B). Strip leading 24B padding.
        g = "0x" + topics[1][-40:]
        i = "0x" + topics[2][-40:]
        pairs.add((g.lower(), i.lower()))
    return sorted(pairs)


def get_pair_purchase_ids(
    rpc_url: str, genius: str, idiot: str
) -> list[int]:
    """Call Account.getPairPurchaseIds(g, i) -> uint256[].

    Returns the FULL history (cumulative across cycles). Caller must filter
    by isPurchaseAudited to find unsettled pids.
    """
    data = SEL_GET_PAIR_PURCHASE_IDS + encode_address(genius) + encode_address(idiot)
    result = rpc(
        "eth_call",
        [{"to": ACCOUNT, "data": data}, "latest"],
        rpc_url,
    )
    # result is hex-encoded ABI: offset (32B) + length (32B) + items
    raw = result.removeprefix("0x")
    if len(raw) < 128:
        return []
    length = hex_to_int(raw[64:128])
    pids = []
    for k in range(length):
        start = 128 + k * 64
        pids.append(hex_to_int(raw[start : start + 64]))
    return pids


def is_purchase_audited(rpc_url: str, pid: int) -> bool:
    data = SEL_IS_PURCHASE_AUDITED + encode_uint256(pid)
    result = rpc(
        "eth_call",
        [{"to": ACCOUNT, "data": data}, "latest"],
        rpc_url,
    )
    return hex_to_int(result.removeprefix("0x")) != 0


def get_unaudited_pids(rpc_url: str, genius: str, idiot: str) -> list[int]:
    """Filter getPairPurchaseIds to only the pids that are still unaudited.

    Idempotency: re-runs of this script skip pairs whose pids are all
    already settled, instead of trying to forceSettle audited pids
    (which reverts with PurchaseAlreadyAudited).
    """
    pids = get_pair_purchase_ids(rpc_url, genius, idiot)
    return [p for p in pids if not is_purchase_audited(rpc_url, p)]


def compute_score(
    rpc_url: str, genius: str, idiot: str, pids: list[int]
) -> int | None:
    """Call Audit.computeScore(g, i, pids) -> int256. Returns None on revert."""
    if not pids:
        return None
    # ABI: f(g, i, pids[]) → tail-encode pids array
    head = (
        SEL_COMPUTE_SCORE
        + encode_address(genius)
        + encode_address(idiot)
        + encode_uint256(0x60)  # offset to dynamic arg #3 (3 * 32 = 96 bytes from start of args)
    )
    tail = encode_uint256(len(pids)) + "".join(encode_uint256(p) for p in pids)
    data = head + tail
    try:
        result = rpc(
            "eth_call",
            [{"to": AUDIT, "data": data}, "latest"],
            rpc_url,
        )
    except RuntimeError as e:
        print(f"    [warn] computeScore reverted: {e}", file=sys.stderr)
        return None
    raw = result.removeprefix("0x")
    if not raw:
        return None
    # int256 — interpret as two's complement
    n = hex_to_int(raw[:64])
    if n >= 2**255:
        n -= 2**256
    return n


def get_account_nonce(rpc_url: str, addr: str) -> int:
    """Return the LATEST mined nonce for an address."""
    return hex_to_int(rpc("eth_getTransactionCount", [addr, "latest"], rpc_url))


def wait_for_nonce_advance(rpc_url: str, addr: str, expected_at_least: int, timeout_s: float = 30.0) -> int:
    """Block until nonce >= expected_at_least, or timeout. Returns observed nonce."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            n = get_account_nonce(rpc_url, addr)
            if n >= expected_at_least:
                return n
        except Exception:
            pass
        time.sleep(2.0)
    return get_account_nonce(rpc_url, addr)


def submit_force_settle(
    rpc_url: str, genius: str, idiot: str, score: int, deployer_key: str, delay_s: int,
    salt_tag: str,
) -> bool:
    """Run forge ForceSettleNew schedule + wait + execute. Returns True on success."""
    if shutil.which("forge") is None:
        print("    [error] forge not in PATH — install foundry to submit", file=sys.stderr)
        return False

    env = {
        **os.environ,
        "GENIUS": genius,
        "IDIOT": idiot,
        "QUALITY_SCORE": str(score),
        "DEPLOYER_KEY": deployer_key,
        # Unique per run + per pair so re-runs don't collide on the
        # TimelockController operation id (= keccak(targets, values,
        # payloads, predecessor, salt)).
        "SALT_TAG": salt_tag,
    }

    # forge needs foundry.toml + remappings on cwd; both live in contracts/.
    contracts_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts"
    )

    # Derive deployer address from key for nonce sync.
    from eth_account import Account as EthAccount  # local import to avoid hard dep at module load
    deployer_addr = EthAccount.from_key(deployer_key).address

    # Capture nonce before schedule. After schedule we wait until the nonce
    # advances by 1 before issuing execute. This is the real fix for the
    # forge-cache nonce race: --slow only sequences within a single forge
    # invocation, not between them.
    pre_nonce = get_account_nonce(rpc_url, deployer_addr)

    print(f"    [run] schedule g={genius} i={idiot} score={score}", file=sys.stderr)
    sched = subprocess.run(
        [
            "forge", "script",
            "script/ForceSettleNew.s.sol",
            "--rpc-url", rpc_url,
            "--broadcast",
            "--silent",
            "--slow",  # sequential submission to avoid nonce-cache races
        ],
        env={**env, "PHASE": "schedule"},
        cwd=contracts_dir,
        capture_output=True,
        text=True,
    )
    if sched.returncode != 0:
        err_str = (sched.stderr or sched.stdout or "")[:300]
        print(
            f"    [warn] schedule rc={sched.returncode}: {err_str}",
            file=sys.stderr,
        )
        # If the schedule failed for any non-already-scheduled reason, the
        # subsequent execute will revert with TimelockUnexpectedOperationState.
        # Skip the wait + execute entirely; let the operator re-run.
        if "OperationDuplicate" not in err_str and "AlreadyExists" not in err_str:
            return False

    # Wait for the schedule tx to mine — nonce must advance before forge
    # can pick up a fresh nonce for the execute call.
    wait_for_nonce_advance(rpc_url, deployer_addr, pre_nonce + 1, timeout_s=30.0)

    print(f"    [wait] {delay_s}s for timelock", file=sys.stderr)
    time.sleep(delay_s)
    pre_exec_nonce = get_account_nonce(rpc_url, deployer_addr)

    exec_run = subprocess.run(
        [
            "forge", "script",
            "script/ForceSettleNew.s.sol",
            "--rpc-url", rpc_url,
            "--broadcast",
            "--silent",
            "--slow",  # sequential submission to avoid nonce-cache races
        ],
        env={**env, "PHASE": "execute"},
        cwd=contracts_dir,
        capture_output=True,
        text=True,
    )
    if exec_run.returncode != 0:
        print(
            f"    [error] execute rc={exec_run.returncode}: {exec_run.stderr[:200]}",
            file=sys.stderr,
        )
        return False

    # Wait for execute to confirm before returning.
    wait_for_nonce_advance(rpc_url, deployer_addr, pre_exec_nonce + 1, timeout_s=30.0)
    return True


def main() -> int:
    rpc_url = os.environ.get("BASE_RPC_URL", "https://sepolia.base.org")
    dry_run = bool(os.environ.get("DRY_RUN"))
    skip_outcomes = bool(os.environ.get("SKIP_OUTCOMES"))
    deployer_key = os.environ.get("DEPLOYER_KEY")
    delay_s = int(os.environ.get("PER_PAIR_DELAY_S", "80"))
    pair_filter = os.environ.get("PAIR_FILTER")

    if not dry_run and not deployer_key:
        print("FATAL: DEPLOYER_KEY required (or set DRY_RUN=1)", file=sys.stderr)
        return 1

    latest = hex_to_int(rpc("eth_blockNumber", [], rpc_url))
    from_block = int(os.environ.get("FROM_BLOCK", str(max(0, latest - 100_000))))

    pairs = discover_pairs(rpc_url, from_block, latest)
    print(f"discovered {len(pairs)} unique (genius, idiot) pairs", file=sys.stderr)

    if pair_filter:
        kind, addr = pair_filter.split(":", 1)
        addr = addr.lower()
        if kind == "genius":
            pairs = [(g, i) for g, i in pairs if g == addr]
        elif kind == "idiot":
            pairs = [(g, i) for g, i in pairs if i == addr]
        print(f"  filtered to {len(pairs)} pair(s) by {kind}={addr}", file=sys.stderr)

    settled = 0
    skipped = 0
    errors = 0
    run_started_ts = int(time.time())

    for g, i in pairs:
        try:
            pids = get_unaudited_pids(rpc_url, g, i)
        except Exception as e:
            print(f"  [error] {g} / {i} — getUnauditedPids: {e}", file=sys.stderr)
            errors += 1
            continue

        if not pids:
            print(f"  [skip] {g} / {i} — all pids already audited", file=sys.stderr)
            skipped += 1
            continue

        score: int | None
        if skip_outcomes:
            score = 0
        else:
            score = compute_score(rpc_url, g, i, pids)
            if score is None:
                # Outcomes not finalized; skip and let the operator set
                # outcomes via Escrow.setOutcome before re-running.
                print(
                    f"  [skip] {g} / {i} — {len(pids)} pid(s) but computeScore "
                    "reverted (outcomes pending). Re-run with SKIP_OUTCOMES=1 "
                    "to force-settle at score=0, or set outcomes first.",
                    file=sys.stderr,
                )
                skipped += 1
                continue

        if dry_run:
            print(f"  [dry] {g} / {i} — {len(pids)} pid(s), score={score}")
            continue

        # Unique salt per pair per invocation: fold the start time into
        # the tag so re-runs of the same script never reuse a prior
        # operation id.
        salt_tag = f"force-settle-{run_started_ts}"
        ok = submit_force_settle(rpc_url, g, i, score, deployer_key, delay_s, salt_tag)
        if ok:
            print(f"  [ok] settled {g} / {i} score={score}")
            settled += 1
        else:
            errors += 1

    print(
        f"\nsummary: pairs={len(pairs)} settled={settled} skipped={skipped} errors={errors}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
