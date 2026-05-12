"""Architectural invariants — these tests encode design decisions, not behaviour.

The miner is a **pure pull-model service**. Validators POST to miner endpoints
(`/v1/signal`, `/v1/healthcheck`, etc.); the miner never calls validators and
never reads protocol contracts. This decoupling is load-bearing for P0-04:
when the protocol is paused on-chain, validators drop mutation traffic and
miners naturally idle out — no miner-side pause-awareness code is required.

If someone adds a chain call, a web3 import, or an outbound HTTP call to a
validator mutation endpoint, this test fails and forces a design discussion
before the invariant is silently broken.
"""

from __future__ import annotations

import re
from pathlib import Path

MINER_SRC = Path(__file__).resolve().parent.parent / "djinn_miner"

FORBIDDEN_IMPORT_ROOTS = (
    "web3",
    "eth_account",
    "eth_abi",
    "eth_typing",
    "eth_utils",
    "eth_keys",
    "eth_hash",
    "ethers",
)

VALIDATOR_MUTATION_PATHS = (
    "/v1/signal",
    "/v1/purchase",
    "/v1/commit",
    "/v1/audit",
    "/v1/outcome",
    "/v1/credit",
    "/v1/key/recover",
    "/v1/key-recovery",
)


def _iter_miner_sources() -> list[Path]:
    return [p for p in MINER_SRC.rglob("*.py") if "__pycache__" not in p.parts]


class TestPurePullModel:
    def test_no_evm_library_imports(self) -> None:
        """Miner must not import web3 or any eth_* RPC library.

        Importing these would mean the miner is reading the chain directly
        and needs its own pause-awareness logic. Keep the chain out of the
        miner.
        """
        pattern = re.compile(
            r"^\s*(?:from|import)\s+(" + "|".join(re.escape(root) for root in FORBIDDEN_IMPORT_ROOTS) + r")(?:[.\s]|$)",
            re.MULTILINE,
        )
        offenders: list[str] = []
        for path in _iter_miner_sources():
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(MINER_SRC.parent)}:{line_no}: {match.group(0).strip()}")
        assert not offenders, (
            "Miner imports an EVM library. This breaks the pure pull-model "
            "invariant (P0-04). Adding chain reads to the miner requires a "
            "design discussion first.\n  " + "\n  ".join(offenders)
        )

    def test_no_outbound_validator_mutation_calls(self) -> None:
        """Miner httpx calls must not target validator mutation endpoints.

        The miner may legitimately call out to:
          - the notary sidecar (localhost)
          - the odds API (external data provider)
          - the target URL being attested (user-provided)
          - watchtower/telemetry (external observability)

        It must NOT call validator /v1/signal, /v1/purchase, etc. Those
        endpoints are inbound-only from the miner's perspective.
        """
        http_call_pattern = re.compile(
            r"(httpx\.(?:AsyncClient|Client|get|post|put|patch|delete)"
            r"|(?:await\s+)?(?:_?client|_rc|probe|session|http)\.(?:get|post|put|patch|delete))"
            r"[^\n]*"
        )
        offenders: list[str] = []
        for path in _iter_miner_sources():
            text = path.read_text(encoding="utf-8")
            for match in http_call_pattern.finditer(text):
                snippet = match.group(0)
                for mutation_path in VALIDATOR_MUTATION_PATHS:
                    if mutation_path in snippet:
                        line_no = text.count("\n", 0, match.start()) + 1
                        offenders.append(
                            f"{path.relative_to(MINER_SRC.parent)}:{line_no}: calls validator path {mutation_path!r}"
                        )
        assert not offenders, (
            "Miner makes an outbound HTTP call to a validator mutation "
            "endpoint. Miners are pull-only; validators call miners, not "
            "the reverse. This breaks P0-04.\n  " + "\n  ".join(offenders)
        )
