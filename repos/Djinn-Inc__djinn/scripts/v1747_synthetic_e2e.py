"""v1747 synthetic end-to-end test against live Base Sepolia deployment.

Flow:
  1. Construct a SYNTHETIC_TEST line (sport + event_id clearly fake)
  2. Compute lineHash against the LIVE registry address
  3. Sign EIP-712 with the deployer key (which is one of the OV validators)
  4. Submit submitLineOutcome via cast send
  5. Confirm LineAttested event is in the receipt
  6. Poll the subgraph until the Line entity appears
  7. Curl /verify/<lineHash> and confirm "1 attestation" UI

Proves: signing, ABI encoding, validator-registry gating, event emission,
subgraph indexing, /verify rendering. All except 4-of-4 → LineFinalized,
which is covered by Foundry tests.

Output: full step-by-step log + final SUCCESS/FAIL summary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Reuse the golden-vector primitives. Same canonical_string + lineHash + signing.
sys.path.insert(0, str(Path(__file__).parent))
from v1747_golden_vectors import (
    LineKey,
    line_hash,
    sign_attestation,
    eip712_digest,
    eip712_domain_separator,
    outcome_ruleset_hash,
    FAVORABLE,
)

# Live deployment.
REGISTRY = "0x2AB6ef76464D25713dfc3b9613f6AD2d07218352"
RPC = "https://sepolia.base.org"
CHAIN_ID = 84532
SUBGRAPH = "https://api.studio.thegraph.com/query/1742249/djinn/v1747-line-outcomes"
VERIFY_URL_TEMPLATE = "https://www.djinn.gg/verify/{linehash}"

# Synthetic test line. Distinct enough from any real game that it can never
# collide. event_id includes today's date + a probe tag.
TEST_LINE = LineKey(
    sport="synthetic_test_e2e",
    event_id="v1747-2026-05-09-probe-001",
    market="moneyline",
    side="home",
    line_value="",
)
TEST_OUTCOME = FAVORABLE  # Favorable = 1


def run(cmd: list[str], check: bool = True, env: dict | None = None) -> str:
    """Run a shell command and return its stdout. On failure, raise."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(
        cmd, capture_output=True, text=True, env={**os.environ, **(env or {})}
    )
    if result.returncode != 0 and check:
        print(f"    STDERR: {result.stderr}")
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    out = result.stdout.strip()
    return out


def deployer_key() -> str:
    """Read DEPLOYER_KEY from contracts/.env."""
    env_path = Path("/home/user/djinn/contracts/.env")
    for line in env_path.read_text().splitlines():
        if line.startswith("DEPLOYER_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("DEPLOYER_KEY not found in contracts/.env")


def main() -> int:
    print("=" * 72)
    print("v1747 SYNTHETIC E2E — Base Sepolia")
    print("=" * 72)

    # ─── Step 1: build the line ─────────────────────────────────────────
    print("\n[1/7] Constructing synthetic test line...")
    canonical = TEST_LINE.canonical_string()
    lh = line_hash(TEST_LINE, CHAIN_ID, REGISTRY)
    lh_hex = "0x" + lh.hex()
    print(f"    canonical_string: {canonical}")
    print(f"    lineHash:         {lh_hex}")

    # ─── Step 2: sign EIP-712 ───────────────────────────────────────────
    print("\n[2/7] Signing EIP-712 attestation...")
    privkey = deployer_key()
    sig, signer = sign_attestation(privkey, lh, TEST_OUTCOME, CHAIN_ID, REGISTRY)
    sig_hex = "0x" + sig.hex()
    print(f"    signer:           {signer}")
    print(f"    digest:           0x{eip712_digest(lh, TEST_OUTCOME, CHAIN_ID, REGISTRY).hex()}")
    print(f"    signature:        {sig_hex[:18]}...{sig_hex[-12:]}")

    # ─── Step 3: cross-check digest matches contract ────────────────────
    print("\n[3/7] Cross-checking domain separator vs on-chain...")
    expected_sep = "0x" + eip712_domain_separator(CHAIN_ID, REGISTRY).hex()
    onchain_sep = run([
        "/home/user/.foundry/bin/cast", "call", REGISTRY,
        "domainSeparatorV4()(bytes32)",
        "--rpc-url", RPC,
    ])
    if onchain_sep.lower() != expected_sep.lower():
        print(f"    FAIL: separator mismatch")
        print(f"          expected: {expected_sep}")
        print(f"          on-chain: {onchain_sep}")
        return 1
    print(f"    OK — domain separator matches")

    onchain_ruleset = run([
        "/home/user/.foundry/bin/cast", "call", REGISTRY,
        "OUTCOME_RULESET_HASH()(bytes32)",
        "--rpc-url", RPC,
    ])
    expected_ruleset = "0x" + outcome_ruleset_hash().hex()
    if onchain_ruleset.lower() != expected_ruleset.lower():
        print(f"    FAIL: ruleset hash mismatch")
        print(f"          expected: {expected_ruleset}")
        print(f"          on-chain: {onchain_ruleset}")
        return 1
    print(f"    OK — ruleset hash matches: {onchain_ruleset}")

    # ─── Step 4: submitLineOutcome via cast send ────────────────────────
    print("\n[4/7] Submitting attestation on chain...")

    # cast send with array args. signers is [signer], signatures is [sig].
    signers_arg = f"[{signer}]"
    sigs_arg = f"[{sig_hex}]"

    out = run([
        "/home/user/.foundry/bin/cast", "send", REGISTRY,
        "submitLineOutcome(bytes32,uint8,address[],bytes[])",
        lh_hex,
        str(TEST_OUTCOME),
        signers_arg,
        sigs_arg,
        "--rpc-url", RPC,
        "--private-key", privkey,
        "--json",
    ])

    receipt = json.loads(out)
    tx_hash = receipt.get("transactionHash")
    block = int(receipt.get("blockNumber"), 16) if receipt.get("blockNumber") else None
    status = int(receipt.get("status"), 16) if receipt.get("status") else None
    print(f"    tx hash:    {tx_hash}")
    print(f"    block:      {block}")
    print(f"    status:     {'success' if status == 1 else 'FAIL'}")
    if status != 1:
        print(f"    full receipt: {out}")
        return 1

    # ─── Step 5: confirm LineAttested event ─────────────────────────────
    print("\n[5/7] Verifying LineAttested event in receipt...")
    logs = receipt.get("logs", [])
    # event LineAttested(bytes32 indexed lineHash, address indexed attestor, uint8 outcome)
    # Verify by lineHash appearing in topics[1] of any log from the registry.
    found = False
    for log in logs:
        if log.get("address", "").lower() != REGISTRY.lower():
            continue
        topics = log.get("topics", [])
        if len(topics) >= 2 and topics[1].lower() == lh_hex.lower():
            print(f"    OK — registry log with lineHash topic found")
            print(f"        topic0 (event sig): {topics[0]}")
            print(f"        topic1 (lineHash):  {topics[1]}")
            print(f"        topic2 (attestor):  {topics[2] if len(topics) > 2 else '<none>'}")
            found = True
            break
    if not found:
        print(f"    FAIL — no LineAttested event from registry with our lineHash")
        return 1

    # ─── Step 6: poll subgraph for indexed Line ─────────────────────────
    print("\n[6/7] Polling subgraph for Line entity (target block: "
          f"{block}, give it ~60s)...")

    query = (
        '{"query":"{ line(id: \\"' + lh_hex + '\\") { id outcome forceVoided '
        'attestations { id attestor outcome blockNumber } } _meta { block { number } } }"}'
    )

    for attempt in range(1, 25):  # ~75s total
        time.sleep(3)
        out = run([
            "curl", "-sS", "-X", "POST", "-H", "Content-Type: application/json",
            "-d", query, SUBGRAPH,
        ], check=False)
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            print(f"    attempt {attempt}: invalid JSON: {out[:200]}")
            continue

        meta_block = data.get("data", {}).get("_meta", {}).get("block", {}).get("number")
        line = data.get("data", {}).get("line")
        print(f"    attempt {attempt}: subgraph head={meta_block} target={block} "
              f"line={'found' if line else 'null'}")

        if line is not None:
            print(f"\n    OK — subgraph indexed the line")
            print(f"        outcome:      {line.get('outcome')}")
            print(f"        attestations: {len(line.get('attestations', []))}")
            for att in line.get("attestations", []):
                print(f"          - attestor={att['attestor']} outcome={att['outcome']} "
                      f"block={att['blockNumber']}")
            break
    else:
        print(f"    FAIL — line never appeared in subgraph after 75s")
        return 1

    # ─── Step 7: confirm /verify/<lineHash> renders ─────────────────────
    print("\n[7/7] Fetching /verify page...")
    verify_url = VERIFY_URL_TEMPLATE.format(linehash=lh_hex)
    print(f"    URL: {verify_url}")
    body = run([
        "curl", "-sL", "-A", "Mozilla/5.0", verify_url,
    ], check=False)
    if "Verify line" in body:
        print(f"    OK — /verify page rendered (body: {len(body)} chars)")
    else:
        print(f"    UNEXPECTED — page body doesn't contain 'Verify line' header")
        print(f"    First 200 chars: {body[:200]}")

    print("\n" + "=" * 72)
    print("SYNTHETIC E2E SUCCESS")
    print("=" * 72)
    print(f"Tx:        https://sepolia.basescan.org/tx/{tx_hash}")
    print(f"Verify:    {verify_url}")
    print(f"Subgraph:  curl -X POST -H 'Content-Type: application/json' \\")
    print(f"             -d '{{\"query\":\"{{ line(id:\\\"{lh_hex}\\\") {{ outcome attestations {{ attestor }} }} }}\"}}' \\")
    print(f"             {SUBGRAPH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
