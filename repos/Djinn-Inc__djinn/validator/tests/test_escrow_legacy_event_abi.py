"""Ensure the pre-V6 SignalPurchased shape stays scannable.

The Escrow UUPS proxy (0xb43BA175...) was deployed 2026-03-22 and upgraded
in place on 2026-04-14. The V6 upgrade added a `purchaseId` field to the
`SignalPurchased` event, changing the canonical signature and therefore
its topic0 hash. Events emitted before the upgrade live on the same proxy
address but carry the old topic0. web3.py's `Contract.events.X.get_logs()`
filters by the loaded ABI's topic0, so a single-shape scan silently drops
the ~3 weeks of pre-V6 history.

This test locks in the dual-ABI invariant:
  * Both event definitions exist in `contracts.py`.
  * Their canonical keccak256 signatures differ.
  * Each contains exactly the expected fields (regression guard against an
    accidental "cleanup" that re-merges the two).
"""

from __future__ import annotations

from eth_utils import keccak

from djinn_validator.chain.contracts import ESCROW_ABI, ESCROW_LEGACY_EVENT_ABI


def _event_entry(abi: list[dict], name: str) -> dict:
    for entry in abi:
        if entry.get("type") == "event" and entry.get("name") == name:
            return entry
    raise AssertionError(f"event {name} not found")


def _canonical_sig(entry: dict) -> str:
    arg_types = ",".join(inp["type"] for inp in entry["inputs"])
    return f"{entry['name']}({arg_types})"


def _topic0(entry: dict) -> bytes:
    return keccak(text=_canonical_sig(entry))


def test_v6_event_has_purchase_id() -> None:
    entry = _event_entry(ESCROW_ABI, "SignalPurchased")
    fields = [i["name"] for i in entry["inputs"]]
    assert fields == [
        "signalId",
        "buyer",
        "purchaseId",
        "notional",
        "feePaid",
        "creditUsed",
        "usdcPaid",
    ]


def test_legacy_event_lacks_purchase_id() -> None:
    entry = _event_entry(ESCROW_LEGACY_EVENT_ABI, "SignalPurchased")
    fields = [i["name"] for i in entry["inputs"]]
    assert fields == [
        "signalId",
        "buyer",
        "notional",
        "feePaid",
        "creditUsed",
        "usdcPaid",
    ]


def test_topic0_hashes_differ() -> None:
    """If these ever match, a single ABI can scan both and the shadow
    contract becomes redundant. Until then, a single-ABI scan would miss
    pre-V6 history and this test is the tripwire."""
    v6 = _topic0(_event_entry(ESCROW_ABI, "SignalPurchased"))
    legacy = _topic0(_event_entry(ESCROW_LEGACY_EVENT_ABI, "SignalPurchased"))
    assert v6 != legacy


def test_canonical_signatures() -> None:
    """Pin the exact strings so any accidental field-type change fails loudly."""
    v6_sig = _canonical_sig(_event_entry(ESCROW_ABI, "SignalPurchased"))
    legacy_sig = _canonical_sig(_event_entry(ESCROW_LEGACY_EVENT_ABI, "SignalPurchased"))
    assert v6_sig == "SignalPurchased(uint256,address,uint256,uint256,uint256,uint256,uint256)"
    assert legacy_sig == "SignalPurchased(uint256,address,uint256,uint256,uint256,uint256)"
