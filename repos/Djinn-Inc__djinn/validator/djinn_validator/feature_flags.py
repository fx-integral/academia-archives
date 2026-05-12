"""Runtime feature flags for staged protocol rollouts.

Each flag is a single boolean that controls whether a piece of new behavior
is enabled on this validator. Flags default to OFF on the `main` branch and
can be flipped ON per-validator via env vars (DJINN_FF_<FLAG_NAME>=true).

Pattern:

    from djinn_validator.feature_flags import flags

    if flags.circuit_breaker:
        run_new_scoring_loop()
    else:
        run_old_scoring_loop()

The kill switch is the same env var: setting DJINN_FF_<FLAG_NAME>=false (or
removing it) disables the flag without redeploying. Validators can be
restarted to pick up new flag state, but the flag value is read once at
startup so behavior is consistent for the lifetime of the process.

Every active flag must be listed in docs/feature-flags.md with a removal
plan. Dead flags accumulate.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, fields

# Load .env so DJINN_FF_* values are visible regardless of import order.
# Without this, importing feature_flags before config.load_dotenv() runs
# would silently see all flags as OFF, which is a confusing failure mode.
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except ImportError:
    # python-dotenv is a hard dependency in production. If it's missing,
    # warn loudly so an operator can spot the misconfiguration instead
    # of silently seeing all flags OFF.
    import warnings as _warnings

    _warnings.warn(
        "python-dotenv not installed; feature flags will only see process env, " "not values declared in .env files",
        stacklevel=1,
    )


# v1567: auto-enable settlement flags on Sepolia (BASE_CHAIN_ID=84532).
# Validators already submit metagraph weights and registration txs on-chain
# as their core function; submitting OutcomeVoting.submitVote() is the same
# category of operator duty, not an opt-in. Under mainnet (BASE_CHAIN_ID=8453)
# the default stays False until a deliberate mainnet crank-up. Explicit env
# vars (DJINN_FF_BATCH_SETTLEMENT_HTTP=false) still override in either direction.
# See MAINNET_BLOCKERS P0-01 and audit_set.py for the same BASE_CHAIN_ID pattern.
try:
    _base_chain_id = int(os.environ.get("BASE_CHAIN_ID", "84532"))
except ValueError:
    _base_chain_id = 84532
_on_sepolia: bool = _base_chain_id == 84532


def _bool_env(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class FeatureFlags:
    """All active feature flags. Each must be documented in docs/feature-flags.md."""

    circuit_breaker: bool = _bool_env("DJINN_FF_CIRCUIT_BREAKER", False)
    """CUSUM-based miner deviation tracking + on-flag TLSNotary appeal mechanism.

    When OFF: validators score miners only by current consensus agreement.
    When ON: per-miner CUSUM scores are tracked, flagged miners are notified,
    appeal flow is active. See project_consensus_circuit_breaker.md.
    """

    canonical_odds: bool = _bool_env("DJINN_FF_CANONICAL_ODDS", False)
    """Canonical internal odds schema with miner-side adapters.

    When OFF: validator uses Odds API shape directly.
    When ON: validator queries miners for canonical-schema responses and
    runs consensus over those. See project_canonical_odds_schema.md.
    """

    appeal_mechanism: bool = _bool_env("DJINN_FF_APPEAL_MECHANISM", False)
    """TLSNotary-backed appeal endpoint for flagged miners.

    Depends on circuit_breaker. When ON: validator accepts appeal submissions
    from flagged miners and resolves them. When OFF: flagged miners can only
    accept the slash, not appeal.
    """

    purchase_v2: bool = _bool_env("DJINN_FF_PURCHASE_V2", False)
    """Phase 2 purchase flow: oracle attack mitigation, vectorHash, batch settlement.

    When OFF: validator accepts V1 purchases via legacy purchase() contract function.
    When ON: validator accepts V2 purchases via purchaseV2() with vectorHash field
    and cross-checks buyer-claimed availability against independent miner consensus.
    """

    new_miner_zero_weight: bool = _bool_env("DJINN_FF_NEW_MINER_ZERO_WEIGHT", False)
    """Bootstrap delay window for newly-registered miner hotkeys.

    When OFF: new miners start at default weight after registration.
    When ON: new miners start at zero weight until they pass a minimum sample
    count, closing the registration-window Sybil hole.
    """

    quorum_strict: bool = _bool_env("DJINN_FF_QUORUM_STRICT", False)
    """Per-call-type quorum policy for high-stakes validator operations.

    When OFF: client races first responder (2-of-N for purchases).
    When ON: high-stakes calls require Q-of-N agreement (3+ for purchase
    verification, settlement). See project_incentive_attack_surface.md.
    """

    reliability_weight: bool = _bool_env("DJINN_FF_RELIABILITY_WEIGHT", False)
    """Amplify notary_reliability and shield_installed in the scoring formula.

    When OFF: reliability contributes ~1% of final weight (10% bonus on uptime).
    When ON: miners with >=5 lifetime notary duties assigned have their score
    multiplied by max(0.2, notary_reliability). Miners with shield_installed=true
    get a +20% bonus. Target: make per-UID scaling sub-linear for sybils that
    clone miner boxes without cloning notary infrastructure.
    """

    proof_complexity_weight: bool = _bool_env("DJINN_FF_PROOF_COMPLEXITY_WEIGHT", False)
    """Amplify score by average per-session TLSN work (bytes + duration).

    When OFF: scoring treats one 100-byte session identical to one 100KB
    session; a sybil cluster with 30 UIDs sprays trivial sessions and wins.
    When ON: final score is multiplied by a [1.0, 2.0] log-scaled factor
    driven by max(avg_prover_bytes, avg_notary_bytes) measured from
    lifetime_attestation_proof_bytes / lifetime_attestations_valid and
    lifetime_notary_proof_bytes / lifetime_notary_duties_completed.
    Reference point is 1 KB (multiplier = 1.0); 64 KB ≈ 1.6x; 1 MB ≈ 2.0x
    (capped). Miners serving heavy pages (debust/firmrecord-style large
    sites, long TLS transcripts) earn more per session than sybils spraying
    tiny sessions. Rewards real notary infrastructure investment.
    Depends on the v1173 instrumentation that populates the per-session
    work counters.
    """

    strict_peer_hotkey: bool = _bool_env("DJINN_FF_STRICT_PEER_HOTKEY", False)
    """Require non-empty matching hotkey on peer /health probes.

    When OFF (default): a peer response with an empty `hotkey` field is
    accepted — the identity check falls back to uid-match only. This is
    the v1351 backwards-compat path for validators running pre-v1351
    code that don't yet ship a `hotkey` field. Acceptances are logged
    at INFO with `peer_hotkey_missing` so operators can track rollout.

    When ON: a peer is rejected unless it returns a non-empty `hotkey`
    that matches the metagraph's `hotkeys[uid]` (or `axons[uid].hotkey`
    fallback). Flip this on after watchtower confirms every validator
    in `/network/validators` is on v1351+. Closes the empty-hotkey
    bypass flagged by fresh-eyes audit on v1352.
    """

    batch_settlement_http: bool = _bool_env("DJINN_FF_BATCH_SETTLEMENT_HTTP", _on_sepolia)
    """Distributed HTTP batch settlement runtime (task #9).

    When OFF: the /v1/mpc/batch/* endpoints return 503. Only the local
    trusted-dealer simulator (simulate_distributed_batch_settle) runs,
    which tests the math but doesn't move real audit settlements.

    When ON: peers accept batch session invitations, run the per-purchase
    polynomial-eval gate chain, accumulate per-purchase output shares
    into a running sum share locally (never opening per-purchase gains),
    and return only the final sum share on /v1/mpc/batch/open. See
    project_bpa_wpa_durability_2026_04_12.md for why the per-purchase
    shares must stay sealed across the whole batch.
    """

    batch_settlement_http_submit: bool = _bool_env("DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT", _on_sepolia)
    """Promote the distributed batch settlement from observe-only to submit-on-chain.

    Depends on batch_settlement_http. When OFF (default): the distributed
    path runs as a shadow observer and the on-chain vote is submitted only
    when local trusted-dealer settlement succeeds. Under SHAMIR_MIN/MAX=2
    the local path cannot succeed (any single validator holds <threshold
    shares), so nothing settles.

    When ON: if local settlement returns None but the distributed shadow
    completes successfully, submit the distributed aggregate on-chain.
    This is the path that closes P0-01 under 2-of-2 Shamir — the only
    topology where a committee of validators can agree on the audit
    outcome without any one of them holding full reconstruction authority.

    Known approximation: total_notional from the distributed path sums
    all PurchaseInputs.notional including voids (local path excludes
    voids per CF-06). Economic impact is bounded — voids are ~0% in
    sports books and only affect SLA denominator. Refine with an MPC-
    native non-void notional aggregate before mainnet gas crank-up.
    """

    def as_dict(self) -> dict[str, bool]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def enabled(self) -> Iterator[str]:
        for f in fields(self):
            if getattr(self, f.name):
                yield f.name

    def summary(self) -> str:
        on = list(self.enabled())
        if not on:
            return "feature flags: all OFF"
        return f"feature flags ON: {', '.join(on)}"


flags = FeatureFlags()
