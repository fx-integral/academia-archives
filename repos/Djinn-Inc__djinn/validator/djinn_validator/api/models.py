"""Pydantic request/response models for the validator REST API."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_HEX_RE = re.compile(r"^(0x)?[0-9a-fA-F]+$")
_SIGNAL_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,256}$")
_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_EVENT_ID_RE = re.compile(r"^[a-zA-Z0-9_\-:.]{1,256}$")


def _validate_hex(v: str, field_name: str) -> str:
    if not _HEX_RE.match(v):
        raise ValueError(f"{field_name} must be a hex string")
    return v


def _validate_signal_id(v: str) -> str:
    if not _SIGNAL_ID_RE.match(v):
        raise ValueError("signal_id must be 1-256 alphanumeric chars, hyphens, or underscores")
    return v


class BeaverTripleData(BaseModel):
    """Pre-computed Beaver triple for MPC gate computation."""

    a: str = Field(max_length=66)  # Hex-encoded field element
    b: str = Field(max_length=66)
    c: str = Field(max_length=66)


class CandidateLine(BaseModel):
    """A single candidate line in a /v1/check request.

    Mirrors the miner-side CandidateLine schema so the validator can reject
    malformed payloads before fanning out to 15 miners (and burning their
    uptime metrics on 422 responses).
    """

    index: int = Field(ge=1, le=2000)
    sport: str = Field(max_length=128)
    event_id: str = Field(max_length=256)
    home_team: str = Field(max_length=256)
    away_team: str = Field(max_length=256)
    market: str = Field(max_length=64)
    line: float | None = Field(default=None)
    side: str = Field(max_length=256)


class CheckRequest(BaseModel):
    """POST /v1/check — up to 20 candidate lines for parallel miner fan-out."""

    lines: list[CandidateLine] = Field(min_length=1, max_length=20)


# StoreShareRequest / StoreShareResponse (POST /v1/signal — legacy
# plaintext-share fan-out) were removed 2026-05-04 alongside the
# endpoint. /v1/signal/bundle is the only supported share-distribution
# path; see ShareBundleEntry / StoreShareBundleRequest below.


class ShareBundleEntry(BaseModel):
    """One per-validator entry in a storeShareBundle request.

    The genius client SealedBox-encrypts the plaintext Shamir share_y to the
    target validator's x25519 pubkey. The receiving validator finds its own
    entry by matching target_address against its signer EOA, decrypts to
    recover share_y, and stores all OTHER entries verbatim as forwarding
    blobs (peer recovery).
    """

    target_address: str = Field(max_length=42, description="Target validator signer EOA (0x + 40 hex)")
    share_x: int = Field(ge=1, le=2000)
    share_ciphertext: str = Field(max_length=8192, description="Hex-encoded SealedBox(share_y_bytes)")
    index_ciphertext: str = Field(default="", max_length=8192, description="Hex-encoded SealedBox(index_y_bytes)")

    @field_validator("share_ciphertext")
    @classmethod
    def _validate_share_ct(cls, v: str) -> str:
        return _validate_hex(v, "share_ciphertext")

    @field_validator("index_ciphertext")
    @classmethod
    def _validate_index_ct(cls, v: str) -> str:
        if not v:
            return v
        return _validate_hex(v, "index_ciphertext")


class StoreShareBundleRequest(BaseModel):
    """POST /v1/signal/bundle — encrypted-bundle fan-out for share recovery.

    The genius sends THE SAME bundle to every OV signer. Each validator
    decrypts its own entry locally and persists the rest as forwarding blobs.
    See project_share_recovery_design_2026_05_03.md.
    """

    signal_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    # 2026-05-04: tightened from max_length-only to a strict 0x + 40 hex
    # regex. Legacy /v1/signal handler had an explicit _ETH_ADDR_RE.match
    # check; when /v1/signal was removed the equivalent protection moved
    # here so a malformed genius_address (e.g. "0xGenius") gets a 422
    # before reaching downstream chain lookups.
    genius_address: str = Field(max_length=42, pattern=r"^0x[0-9a-fA-F]{40}$")
    shamir_threshold: int = Field(ge=1, le=2000)
    bundle: list[ShareBundleEntry] = Field(min_length=1, max_length=64)
    precomputed_triples: list[BeaverTripleData] = Field(default_factory=list, max_length=200)


class StoreShareBundleResponse(BaseModel):
    signal_id: str
    own_share_stored: bool
    forwarding_count: int


class ShareRecoveryResponse(BaseModel):
    """GET /v1/share-recovery/{signal_id}/{target_address}.

    Returns the forwarding ciphertext targeted at the requested validator.
    No auth: ciphertext is encrypted to target's pubkey, peer-readable is
    fine. Returns 404 if no forwarding entry exists locally.
    """

    signal_id: str
    target_address: str
    share_x: int
    share_ciphertext: str
    index_ciphertext: str
    shamir_threshold: int


class PurchaseRequest(BaseModel):
    """POST /v1/signal/{id}/purchase — Buyer requests a signal purchase."""

    buyer_address: str = Field(max_length=256)
    sportsbook: str = Field(max_length=256)
    available_indices: list[int] = Field(min_length=1, max_length=2000)
    buyer_signature: str = Field(
        default="",
        max_length=2048,
        description="EIP-191 or EIP-1271 (smart wallet) signature proving buyer_address ownership",
    )
    # MPC batch settlement Phase 1 fields (optional, backwards compatible).
    # These carry the per-line BPA/WPA vectors the buyer observed at
    # purchase time, scaled to ODDS_PRECISION (1e6) integer units. The
    # validator stores them keyed by (signal_id, buyer) so that a future
    # audit settlement can look up exactly which market prices were live
    # when this purchase happened — without trusting the buyer to
    # re-supply them at settlement time.
    #
    # Old clients that omit these fields still work. Vectors are only
    # collected (not yet used for settlement) until the contract-side
    # Phase 2 upgrade lands.
    bpas: list[int] | None = Field(
        default=None,
        max_length=2000,
        description="Per-line best-price aggregates at the buyer's books, scaled by 1e6",
    )
    wpas: list[int] | None = Field(
        default=None,
        max_length=2000,
        description="Per-line worst-price aggregates at the buyer's books, scaled by 1e6",
    )
    bpa_mode: bool | None = Field(
        default=None,
        description="Whether this purchase was priced in BPA mode (True) or WPA mode (False)",
    )
    # Oracle attack mitigation (additive). When provided, the validator
    # independently queries the miner network for the current line state
    # at these books and cross-checks the buyer's available_indices claim
    # against the validator's observation. A buyer that claims indices
    # the validator doesn't see as available is rejected as a possible
    # binary-search probe of the real signal index.
    #
    # Old clients that omit this field still work (validator falls back
    # to trusting the buyer's claim, with a deprecation warning logged).
    # The strict-vs-shadow rejection mode is gated by DJINN_FF_PURCHASE_V2.
    buyer_books: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Buyer's preferred sportsbooks for the validator's independent availability check",
    )

    @field_validator("buyer_address")
    @classmethod
    def validate_buyer_address(cls, v: str) -> str:
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("buyer_address must be a valid Ethereum address (0x + 40 hex chars)")
        return v

    @field_validator("available_indices")
    @classmethod
    def validate_indices_range(cls, v: list[int]) -> list[int]:
        for idx in v:
            if idx < 1 or idx > 2000:
                raise ValueError(f"available_indices values must be 1-2000, got {idx}")
        if len(set(v)) != len(v):
            raise ValueError("available_indices must not contain duplicates")
        return v

    @field_validator("bpas", "wpas")
    @classmethod
    def validate_odds_vector(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        for entry in v:
            if entry < 0:
                raise ValueError(f"BPA/WPA entries must be non-negative, got {entry}")
            # The ODDS_PRECISION-scaled cap matches MAX_ODDS in Escrow.sol
            # (1_000_000_000 = 1000x). Anything above is out of protocol.
            if entry > 1_000_000_000:
                raise ValueError(f"BPA/WPA entries must be <= 1_000_000_000 (1000x), got {entry}")
        return v


class PurchaseResponse(BaseModel):
    signal_id: str
    status: str
    available: bool | None = None
    encrypted_key_share: str | None = None  # Hex-encoded Shamir share y-value
    share_x: int | None = None  # Shamir share x-coordinate
    message: str = ""
    mpc_participants: int | None = None  # Number of validators in MPC (diagnostic)
    mpc_failure_reason: str | None = None  # Diagnostic: why MPC returned unavailable


class PurchaseOddsGossipRequest(BaseModel):
    """POST /v1/purchase_odds/record — peer validator broadcasts BPA/WPA.

    The purchase-handler validator calls this endpoint on every committee
    peer after recording BPA/WPA locally, so the vectors are available
    everywhere at audit-settlement time. Without this, only the validator
    that served the original POST /v1/signal/{id}/purchase holds the
    per-line BPA/WPA, and batch settlement cannot assemble PurchaseInputs
    on any other validator.
    """

    signal_id: str = Field(max_length=256)
    buyer_address: str = Field(max_length=256)
    bpas: list[int] = Field(min_length=1, max_length=2000)
    wpas: list[int] = Field(min_length=1, max_length=2000)
    bpa_mode: bool

    @field_validator("signal_id")
    @classmethod
    def _validate_signal_id(cls, v: str) -> str:
        return _validate_signal_id(v)

    @field_validator("buyer_address")
    @classmethod
    def _validate_buyer_address(cls, v: str) -> str:
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("buyer_address must be a valid Ethereum address (0x + 40 hex chars)")
        return v

    @field_validator("bpas", "wpas")
    @classmethod
    def _validate_odds(cls, v: list[int]) -> list[int]:
        for entry in v:
            if entry < 0:
                raise ValueError(f"BPA/WPA entries must be non-negative, got {entry}")
            if entry > 1_000_000_000:
                raise ValueError(f"BPA/WPA entries must be <= 1_000_000_000, got {entry}")
        return v


class PurchaseOddsGossipResponse(BaseModel):
    recorded: bool
    duplicate: bool = False


class AuditGossipRequest(BaseModel):
    """POST /v1/audit/gossip — peer validator broadcasts a new audit_set entry.

    When a sender's audit_bootstrap finds a (genius, idiot, signal_id,
    purchase_id) tuple from chain (or subgraph), it gossips to peers so
    they can populate their audit_set_store within seconds of the chain
    commit, rather than waiting for their own next bootstrap cycle.

    Receivers MUST verify the tuple against chain RPC before adding —
    the on-chain Escrow.purchases(pid) struct must report the same
    signalId AND the signal's genius must match. A malicious or
    out-of-sync peer can claim any tuple, but chain verification means
    they can only nudge receivers toward truths chain itself confirms.
    """

    genius: str = Field(max_length=42, pattern=r"^0x[0-9a-fA-F]{40}$")
    idiot: str = Field(max_length=42, pattern=r"^0x[0-9a-fA-F]{40}$")
    signal_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    purchase_id: int = Field(ge=1, le=10**18)
    # source_uid is informational; signature auth (X-Hotkey) is the
    # security boundary. Mirrors OutcomeGossipRequest.
    source_uid: int = Field(ge=0, le=10_000)


class AuditGossipResponse(BaseModel):
    accepted: bool
    duplicate: bool
    reason: str  # "added" | "duplicate" | "chain_mismatch" | etc.


class OutcomeGossipRequest(BaseModel):
    """POST /v1/outcomes/gossip — peer validator broadcasts a resolved outcome.

    After a validator's OutcomeAttestor resolves a signal locally (ESPN game
    final + line outcomes derived), it gossips the result to every committee
    peer. Receivers replay-verify by independently fetching ESPN for the same
    game; on match the receiver records the outcome locally without re-doing
    the resolution work; on mismatch the discrepancy is logged for rung-3
    miner-attestation escalation. See docs/outcome-layer-plan.md.

    The receiver MUST already have the signal registered locally (via the
    normal purchase pipeline). If the signal is unknown, the gossip is
    rejected with 404 and the sender is expected to wait one purchase-pipeline
    cycle before retrying.
    """

    signal_id: str = Field(max_length=256)
    # Outcomes for ALL lines on this signal, in registration order.
    # Each value is the int form of the Outcome enum:
    # 0=Pending, 1=Favorable, 2=Unfavorable, 3=Void.
    # Cap matches PurchaseOddsGossipRequest.bpas (2000) — signals with
    # 100+ decoy lines are common (see DEV-042 v2 off-chain decoys).
    # Original cap of 64 caused HTTP 422 rejections fleet-wide on
    # 100-line signals, blocking all gossip on first resolution.
    outcomes: list[int] = Field(min_length=1, max_length=2000)
    # Raw ESPN summary used for the resolution. Optional; receiver only
    # consults it for debug/dispute logs (replay-verify is the authoritative
    # check). Keys: home_score, away_score, status, home_team, away_team.
    raw_espn_summary: dict[str, str | int] = Field(default_factory=dict)
    # The UID that produced the resolution. Cross-checked against
    # X-Hotkey via the metagraph at receive time.
    source_uid: int = Field(ge=0, le=10_000)
    # Phase A1.8: carry pair metadata so receiver can register the signal
    # in audit_set_store on-receive instead of waiting for chain bootstrap
    # (~30 min). Optional for backward compatibility — older senders won't
    # set these. When all three are present AND signal not yet in
    # audit_set_store, receiver calls add_signal(genius, idiot, 0,
    # signal_id, purchase_id) before record_outcomes. Validators are signed
    # OV signers so a malicious peer providing wrong pair metadata is the
    # same threat surface as forging votes — slashable in the future audit
    # contract upgrade.
    genius: str | None = None
    idiot: str | None = None
    purchase_id: int | None = Field(default=None, ge=0)
    # v1679 (P1-36 partial): for older signals committed without game_date,
    # the OutcomeAttestor's ESPN lookup back-walks 30 days searching team
    # name matches. Different validators may match different historical
    # games → divergent outcomes → divergent quality_scores → divergent
    # scoreHashes → no quorum. When the resolving validator found the game
    # via back-walk, it now propagates the discovered game_date so receivers
    # can lock onto the same date during replay-verify. Optional for
    # backward compat. Format: "YYYYMMDD" (UTC).
    game_date: str | None = Field(default=None, max_length=8, pattern=r"^\d{8}$|^$")
    # v1747 Phase 3: additive EIP-712 line attestation sigs. The sender's
    # OV signer EOA (the same key registered in OutcomeVoting.isValidator)
    # signs each line's (lineHash, outcome, ruleset) tuple; receivers verify
    # the sig, confirm the signer is in the validator set, and persist to
    # PeerAttestationStore so the threshold-of-4 submit path can fire
    # without each peer re-deriving from ESPN.
    #
    # Both fields are optional for back-compat with v1746 senders. When
    # present, ``eoa_sigs`` must align 1:1 with ``outcomes`` (one sig per
    # line in registration order; PENDING outcomes carry empty-string sigs).
    # Receivers tolerate missing/short eoa_sigs by skipping per-line storage
    # without rejecting the gossip — the legacy outcome propagation still
    # lands.
    eoa: str | None = Field(default=None, max_length=42)
    eoa_sigs: list[str] | None = Field(default=None, max_length=2000)

    @field_validator("eoa")
    @classmethod
    def _validate_eoa(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("eoa must be a valid Ethereum address")
        return v

    @field_validator("eoa_sigs")
    @classmethod
    def _validate_eoa_sigs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for entry in v:
            if entry == "":
                continue
            if not entry.startswith("0x"):
                raise ValueError("eoa_sigs entries must be 0x-prefixed hex")
            # 65-byte sig = 130 hex chars + 0x prefix = 132 chars total.
            if len(entry) != 132:
                raise ValueError(f"eoa_sigs entry must be 132 chars (0x + 130), got {len(entry)}")
        return v

    @field_validator("signal_id")
    @classmethod
    def _validate_signal_id(cls, v: str) -> str:
        return _validate_signal_id(v)

    @field_validator("outcomes")
    @classmethod
    def _validate_outcomes(cls, v: list[int]) -> list[int]:
        for entry in v:
            if entry < 0 or entry > 3:
                raise ValueError(f"Outcome enum values must be 0..3, got {entry}")
        return v

    @field_validator("genius", "idiot")
    @classmethod
    def _validate_eth_address(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("genius/idiot must be a valid Ethereum address")
        return v


class OutcomeGossipResponse(BaseModel):
    accepted: bool
    duplicate: bool = False
    reason: str = ""


class OutcomeRequest(BaseModel):
    """POST /v1/signal/{id}/outcome — Submit an outcome attestation."""

    signal_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    event_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-:.]+$")
    outcome: int = Field(ge=0, le=3)  # 0=Pending, 1=Favorable, 2=Unfavorable, 3=Void
    validator_hotkey: str = Field(max_length=256)


class OutcomeResponse(BaseModel):
    signal_id: str
    outcome: int
    consensus_reached: bool
    consensus_outcome: int | None = None


class RegisterSignalRequest(BaseModel):
    """POST /v1/signal/{id}/register — Register for blind outcome tracking.

    Accepts the full set of decoy lines (2 to 2000, committed on-chain via
    linesHash).  The validator resolves ALL lines against game results,
    producing N outcomes.  The real outcome is selected later by batch MPC
    at the audit-set level, so no individual signal outcome is ever revealed.
    """

    sport: str = Field(max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    event_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-:.]+$")
    home_team: str = Field(max_length=256)
    away_team: str = Field(max_length=256)
    lines: list[str] = Field(min_length=2, max_length=2000)
    genius_address: str = Field(default="", max_length=256)
    idiot_address: str = Field(default="", max_length=256)
    notional: int = Field(default=0, ge=0)
    odds: int = Field(default=1_000_000, ge=0)
    sla_bps: int = Field(default=10_000, ge=0, le=100_000)
    cycle: int = Field(default=0, ge=0)
    # P1-36 (v1676): client-provided game date so the OutcomeAttestor's ESPN
    # lookup hits the right scoreboard immediately instead of walking back up
    # to 30 days. Without this, signals with no cached game_date can match
    # different historical games on different validators (different team-name
    # ESPN match results) and produce divergent outcome lists → divergent
    # scoreHashes → no quorum convergence. Format: "YYYYMMDD" (UTC). Optional
    # for backward compatibility — when omitted, attestor falls back to back-walk.
    game_date: str | None = Field(default=None, max_length=8, pattern=r"^\d{8}$|^$")

    @field_validator("lines")
    @classmethod
    def validate_lines(cls, v: list[str]) -> list[str]:
        for i, line in enumerate(v):
            if len(line) > 512:
                raise ValueError(f"Line {i} exceeds 512 characters")
            if not line.strip():
                raise ValueError(f"Line {i} is empty")
        return v


class RegisterSignalResponse(BaseModel):
    signal_id: str
    registered: bool
    lines_count: int = 0


class AuditSetStatusResponse(BaseModel):
    """GET /v1/audit/{genius}/{idiot}/status — Audit set status."""

    genius: str
    idiot: str
    cycle: int
    signals_count: int
    resolved_count: int
    ready: bool
    settled: bool


class AuditSummaryResponse(BaseModel):
    """GET /v1/audit/summary — Bucket counts for the audit queue.

    Fleet-level visibility for /djinn audits probes: without this, the only
    way to tell if audits are stalled was to query each genius-idiot pair
    individually. Returns pointwise counts across all sets this validator
    tracks, keyed by lifecycle state.
    """

    total: int
    waiting_for_outcomes: int
    ready_for_settlement: int
    # v1742: subset of ready_for_settlement that the v1716 permanent-
    # abstain counter has evicted. Eligible-to-settle = ready - this.
    # Defaults to 0 so older operators (UID 213 reads VERSION fallback)
    # don't break clients that pin a stricter schema.
    permanently_abstained: int = 0
    settled: int
    total_signals: int
    resolved_signals: int
    # v1744: durable outbound gossip retry queue depth. pending = peers
    # that didn't ack within the in-memory budget and are waiting for the
    # background drain worker to retry. Non-zero values mean fresh-cohort
    # BPA/WPA payloads are mid-flight to recovering peers; zero means the
    # outbound side is converged. Defaults to 0 so older clients don't
    # break.
    gossip_outbox_pending: int = 0
    gossip_outbox_acked: int = 0
    gossip_outbox_failed_terminal: int = 0


class ResolveResponse(BaseModel):
    """POST /v1/signals/resolve — Resolve all pending signals."""

    resolved_count: int
    results: list[dict] = Field(default_factory=list)


class IdentityResponse(BaseModel):
    """GET /v1/identity — Validator identity for peer discovery."""

    base_address: str = ""
    hotkey: str = ""
    version: str = ""


class ValidatorPeerHint(BaseModel):
    """Self-advertised peer hint from one validator about another."""

    uid: int
    hostname: str = ""  # public HTTPS hostname if known
    ip: str = ""
    port: int = 0
    last_seen_ms: int = 0


class HealthResponse(BaseModel):
    """GET /health — Validator health check.

    Includes self-advertise fields used by the static web client to
    discover the network without going through a centralized proxy.
    `public_hostname` is this validator's own publicly-reachable HTTPS
    hostname (set via PUBLIC_HOSTNAME env var). `peers` is a list of
    other validators this one knows about, used by the gossip-style
    discovery in the IPFS-deployable client.
    """

    status: str
    version: str = ""
    uid: int | None = None
    shares_held: int = 0
    pending_outcomes: int = 0
    # Lifetime count of signals whose outcomes have been resolved.
    # Pair with `pending_outcomes` to distinguish a quiet period (pending
    # flat, resolved_total also flat because no games finished) from a
    # resolver wedge (pending climbing, resolved_total flat across iters).
    # Strictly monotonic within a single process lifetime; resets on restart.
    outcomes_resolved_total: int = 0
    # ms epoch of the most recent resolution. None means the current
    # process has never resolved an outcome since startup. For stall
    # detection, compare against server "now" — if `pending_outcomes > 0`
    # and `last_outcome_resolved_ms` is > 6h old, likely resolver wedged.
    last_outcome_resolved_ms: int | None = None
    chain_connected: bool = False
    bt_connected: bool = False
    attest_capable: bool = False
    public_hostname: str = ""  # this validator's own HTTPS hostname (if any)
    peers: list[ValidatorPeerHint] = Field(default_factory=list)
    # Whether this validator's signer EOA is registered in the OutcomeVoting
    # contract and can therefore successfully submit quality-score votes.
    # None = not a writing validator (read-only or no signer configured).
    # False = writing validator whose EOA is missing from OutcomeVoting —
    # every submitVote will revert with NotValidator; operator action needed.
    settlement_registered: bool | None = None
    # The EOA address this validator would use to sign on-chain writes (i.e.
    # submitVote calls against OutcomeVoting). Exposed so a bootstrap script
    # can collect signer EOAs across operators without side-channel messaging.
    # None if no signer is configured. The address alone leaks nothing the
    # on-chain ValidatorUpdated event wouldn't already publish post-registration.
    validator_signer: str | None = None
    # The OutcomeVoting contract address this validator is configured to
    # vote against. Exposed so operators with stale OUTCOME_VOTING_ADDRESS
    # in .env can be diagnosed externally (all five should point at the
    # same live address; a mismatch here explains settlement_registered=false
    # even after timelocked addValidator). Public on-chain state — safe to expose.
    settlement_contract: str | None = None
    # Machine-readable diagnosis when settlement_registered=False. Values:
    #   "stale_env_override" — signer IS on canonical OV; .env has a stale address
    #   "missing_bootstrap"  — signer is not on canonical OV; operator must run AddValidatorSigner
    #   None when either registered=True, can_write=False, or probe failed
    settlement_diagnosis: str | None = None
    # Human-readable one-line remediation paired with settlement_diagnosis.
    # Operators can curl /health and see the exact fix without digging through pm2 logs.
    settlement_remediation: str | None = None
    # Self-reported hotkey. Peers cross-check this against the metagraph's
    # axon[uid].hotkey to detect 8421-port squatting and uid spoofing: if a
    # probe reaches IP:port expecting uid=X (per metagraph) but /health returns
    # a hotkey that doesn't match axons[X].hotkey, the peer is rejected.
    hotkey: str = ""
    # Settlement-path tuning knobs, exposed for fleet-wide config drift
    # detection (v1454). Two common misconfigurations block P0-01 progress
    # silently: `audit_min_batch_size` set to 10 (production default) on a
    # testnet validator where cohorts are 2-6 signals will never promote to
    # ready_for_settlement; `shamir_threshold` set to 7 on a fleet of 6
    # validators makes MPC reconstruction mathematically impossible. Both
    # were invisible from /health until this release — required SSH and
    # grep on each validator's .env to detect.
    audit_min_batch_size: int | None = None
    shamir_threshold: int | None = None
    # Batch-settlement feature flag state, exposed for fleet-wide P0-01
    # rollout observability (v1562). The distributed HTTP batch settlement
    # path is gated behind two env flags that default OFF: operators must
    # flip both to participate in on-chain submitVote. Surfacing these on
    # /health lets the network dashboard show which validators are ready
    # without SSH+grep on each .env. Paired on the UI with a "Submit"
    # column analogous to the OV-registration column.
    batch_settlement_http: bool | None = None
    batch_settlement_http_submit: bool | None = None
    # Watchtower / git-tree diagnostics (v1644). Until this release we
    # could not tell remotely WHY an operator's version was stuck — was
    # their watchtower process dead, was their tree dirty from the v1625
    # self-heal regression, or were they just slow on the next poll?
    # These three fields surface the answer in /health so a fleet-monitor
    # cron can DM operators with a precise diagnosis instead of "your
    # version is behind, figure it out."
    #
    # `git_dirty` = True if `git status --porcelain` is non-empty (any
    # tracked file modified locally). The canonical wedge case: v1625
    # self-heal wrote VERSION on first import → tree dirty → every
    # subsequent `git pull --rebase` refused with "you have unstaged
    # changes." `git_dirty=True` AND `version` not advancing across
    # polls is the smoking gun.
    #
    # `git_dirty_files` = first 5 modified-file paths (truncated, no
    # diff content) so a fleet monitor can show "VERSION,foo.py" without
    # exposing private workspace state.
    #
    # `git_branch` = current branch name. Operators on a non-main branch
    # (e.g. local fork) won't auto-update; surfacing this lets the
    # monitor distinguish "should be on main but isn't" from "is on main
    # but stuck."
    git_dirty: bool | None = None
    git_dirty_files: list[str] = Field(default_factory=list)
    git_branch: str | None = None
    # Code-freshness signals (v1653). Lets dashboards answer "is this
    # validator running current code?" beyond just version-string equality:
    # `git_commit_ts` is the unix-epoch timestamp of HEAD's commit, so a
    # /network UI column can render "deployed 12m ago" / "deployed 4d ago"
    # and visually flag laggards — independent of whether their VERSION
    # file is correct. None on non-git installs.
    # `process_started_ts` is when this validator process last started,
    # which the per-validator detail page can use to distinguish "code
    # deployed long ago, process recently restarted" from "stale code,
    # never restarts."
    git_commit_ts: int | None = None
    process_started_ts: int | None = None
    # Operator diagnostic (v1734): the outbound IP this validator detected
    # for itself via a public reflector at startup. Distinct from the
    # axon IP advertised on the metagraph and from the commitment IPs
    # consumed by miners. Surfaces "what IP did I think I have?" so an
    # operator can sanity-check their commitment before/after publish
    # without SSHing into the box and curling ifconfig.me by hand.
    egress_ip_self_reported: str | None = None


class ReadinessResponse(BaseModel):
    """GET /health/ready — Deep readiness probe."""

    ready: bool
    checks: dict[str, bool] = Field(default_factory=dict)


class AnalyticsRequest(BaseModel):
    """POST /v1/analytics/attempt — Fire-and-forget analytics."""

    event_type: str = Field(max_length=128)
    data: dict = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def validate_data_size(cls, v: dict) -> dict:
        if len(v) > 50:
            raise ValueError(f"data dict must have at most 50 keys, got {len(v)}")
        return v


# ---------------------------------------------------------------------------
# MPC Coordination Models (inter-validator communication)
# ---------------------------------------------------------------------------


class MPCInitRequest(BaseModel):
    """POST /v1/mpc/init — Coordinator invites this validator to an MPC session."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    signal_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    available_indices: list[int] = Field(max_length=2000)
    coordinator_x: int = Field(ge=1, le=255)
    participant_xs: list[int] = Field(max_length=20)
    threshold: int = Field(default=7, ge=1, le=20)
    # This validator's Beaver triple shares (one dict per gate)
    triple_shares: list[dict[str, str]] = Field(default_factory=list, max_length=200)  # hex-encoded
    # This validator's share of the random mask r (hex-encoded)
    r_share_y: str | None = None
    # SPDZ authenticated MPC fields (optional — absent for semi-honest mode)
    authenticated: bool = False
    # Authenticated triple shares: [{a: {y: hex, mac: hex}, b: ..., c: ...}]
    auth_triple_shares: list[dict[str, dict[str, str]]] | None = None
    # MAC key share for this validator (hex-encoded)
    alpha_share: str | None = None
    # Authenticated r share: {y: hex, mac: hex}
    auth_r_share: dict[str, str] | None = None
    # Authenticated secret share: {y: hex, mac: hex}
    auth_secret_share: dict[str, str] | None = None

    @field_validator("available_indices")
    @classmethod
    def validate_mpc_indices(cls, v: list[int]) -> list[int]:
        for idx in v:
            if idx < 1 or idx > 2000:
                raise ValueError(f"available_indices values must be 1-2000, got {idx}")
        return v

    @field_validator("participant_xs")
    @classmethod
    def validate_participant_xs(cls, v: list[int]) -> list[int]:
        for x in v:
            if x < 1 or x > 255:
                raise ValueError(f"participant_xs values must be 1-255, got {x}")
        if len(set(v)) != len(v):
            raise ValueError("participant_xs must not contain duplicates")
        return v


class MPCInitResponse(BaseModel):
    session_id: str
    accepted: bool
    message: str = ""


class MPCRound1Request(BaseModel):
    """POST /v1/mpc/round1 — Submit Round 1 message (d, e values) for a gate."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    # Cap raised from 20 -> 2047 to match commit 4d519db, which raised the
    # triple count validation from 20 to 200 and the broader lineCount cap
    # to 2000. The old gate_idx <= 20 was a leftover defensive bound from
    # the original ten-line era; it silently capped the sequential MPC
    # protocol at 21 gates, causing purchases of any signal with >21
    # executable lines to fail with gate_21_insufficient.
    gate_idx: int = Field(ge=0, le=2047)
    validator_x: int = Field(ge=1, le=255)
    d_value: str = Field(max_length=66)  # Hex-encoded BN254 field element
    e_value: str = Field(max_length=66)  # Hex-encoded BN254 field element

    @field_validator("d_value", "e_value")
    @classmethod
    def validate_hex(cls, v: str) -> str:
        return _validate_hex(v, "d_value/e_value")


class MPCRound1Response(BaseModel):
    session_id: str
    gate_idx: int
    accepted: bool


class MPCResultRequest(BaseModel):
    """POST /v1/mpc/result — Coordinator broadcasts the opened result."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    signal_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    available: bool
    participating_validators: int = Field(ge=0, le=255)


class MPCResultResponse(BaseModel):
    session_id: str
    acknowledged: bool


class MPCComputeGateRequest(BaseModel):
    """POST /v1/mpc/compute_gate — Coordinator requests gate computation."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    # See note on MPCRound1Request.gate_idx for why the bound was raised.
    gate_idx: int = Field(ge=0, le=2047)
    prev_opened_d: str | None = None  # Hex-encoded, None for gate 0
    prev_opened_e: str | None = None  # Hex-encoded, None for gate 0


class MPCComputeGateResponse(BaseModel):
    session_id: str
    gate_idx: int
    d_value: str  # Hex-encoded
    e_value: str  # Hex-encoded
    # SPDZ MAC shares (present only in authenticated mode)
    d_mac: str | None = None  # Hex-encoded
    e_mac: str | None = None  # Hex-encoded


class MPCFinalizeRequest(BaseModel):
    """POST /v1/mpc/finalize — Coordinator requests final output share z_i."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    last_opened_d: str  # Hex-encoded
    last_opened_e: str  # Hex-encoded


class MPCFinalizeResponse(BaseModel):
    session_id: str
    z_share: str  # Hex-encoded output share


class MPCAbortRequest(BaseModel):
    """POST /v1/mpc/abort — Coordinator broadcasts abort due to MAC failure."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    reason: str = Field(max_length=512)
    # See note on MPCRound1Request.gate_idx for why the bound was raised.
    gate_idx: int = Field(ge=0, le=2047)
    offending_validator_x: int | None = None  # x-coord of suspected cheater, if identifiable


class MPCAbortResponse(BaseModel):
    session_id: str
    acknowledged: bool


class MPCSessionStatusResponse(BaseModel):
    """GET /v1/mpc/{session_id}/status — Check MPC session status."""

    session_id: str
    status: str
    available: bool | None = None
    participants_responded: int = 0
    total_participants: int = 0


# ---------------------------------------------------------------------------
# Batch Settlement MPC (task #9, distributed HTTP runtime)
#
# These models define the wire protocol for distributed batch settlement.
# The protocol runs the same polynomial-evaluation gate chain the existing
# /v1/mpc/* endpoints use, but across MULTIPLE purchases in a single
# session, with each peer accumulating per-purchase output shares into a
# running sum share that is only opened once at the end of the batch.
#
# Privacy invariant: the coordinator never sees per-purchase output
# shares. It sees only the final sum share from each peer, which reveals
# nothing about any individual purchase's gain because the sum folds in
# enough unknowns to keep the system underdetermined.
# ---------------------------------------------------------------------------


class BatchPurchaseSpec(BaseModel):
    """One purchase within a batch settlement session.

    The peer looks up its own Shamir share of ``realIndex`` for
    ``signal_id`` in its local share_store — the coordinator does NOT
    transmit shares, keeping the secret distribution identical to a
    purchase flow. Beaver triples for this purchase's gate chain are
    supplied by the coordinator.
    """

    purchase_id: int = Field(ge=0, le=2**53 - 1)
    signal_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    # Per-line gain values as hex-encoded field elements. Derived by the
    # coordinator from public inputs (notional, sla_bps, bpa_mode, bpas,
    # wpas, outcomes) via compute_gain_vector(). Each entry is a
    # uint256-sized hex string.
    gain_vector: list[str] = Field(max_length=2000)
    # Beaver triple shares for this purchase's gate chain (one dict per gate).
    triple_shares: list[dict[str, str]] = Field(default_factory=list, max_length=2000)

    @field_validator("gain_vector")
    @classmethod
    def validate_gain_vector(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("gain_vector must have at least 2 entries")
        for g in v:
            _validate_hex(g, "gain_vector entry")
        return v


class MPCBatchInitRequest(BaseModel):
    """POST /v1/mpc/batch/init — Coordinator invites this validator to a
    batch settlement session covering multiple purchases for the same
    (genius, idiot) pair.
    """

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    coordinator_x: int = Field(ge=1, le=255)
    participant_xs: list[int] = Field(max_length=20)
    threshold: int = Field(default=3, ge=2, le=20)
    # The ordered batch. All purchases must use the same participant set;
    # the audit batch is built per-pair so this is enforced by construction.
    purchases: list[BatchPurchaseSpec] = Field(max_length=200)

    @field_validator("participant_xs")
    @classmethod
    def validate_participant_xs_batch(cls, v: list[int]) -> list[int]:
        for x in v:
            if x < 1 or x > 255:
                raise ValueError(f"participant_xs values must be 1-255, got {x}")
        if len(set(v)) != len(v):
            raise ValueError("participant_xs must not contain duplicates")
        return v


class MPCBatchInitResponse(BaseModel):
    session_id: str
    accepted: bool
    purchase_count: int
    message: str = ""


class MPCBatchComputeGateRequest(BaseModel):
    """POST /v1/mpc/batch/compute_gate — Coordinator drives one gate for
    one purchase within a batch session.
    """

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    purchase_idx: int = Field(ge=0, le=199)
    gate_idx: int = Field(ge=0, le=2047)
    prev_opened_d: str | None = None
    prev_opened_e: str | None = None

    @field_validator("prev_opened_d", "prev_opened_e")
    @classmethod
    def validate_opened(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_hex(v, "prev_opened_d/e")


class MPCBatchComputeGateResponse(BaseModel):
    session_id: str
    purchase_idx: int
    gate_idx: int
    d_value: str
    e_value: str


class MPCBatchAccumulateRequest(BaseModel):
    """POST /v1/mpc/batch/accumulate — After a purchase's last gate, the
    coordinator tells the peer to compute the per-purchase output share
    and FOLD it into the peer's running batch sum share. The peer does
    NOT return the per-purchase share, and MUST NOT expose it via any
    other endpoint — that is the load-bearing privacy invariant.
    """

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    purchase_idx: int = Field(ge=0, le=199)
    # 2-line purchases (n_gates == 0) skip the multiplication gate
    # entirely; for those, last_opened_d/e MUST be null.  Gated purchases
    # require both fields as hex strings.  Codex audit 2026-04-15 caught
    # the previous str-only signature, which silently broke every 2-line
    # purchase in the HTTP batch-settlement runtime.
    last_opened_d: str | None = None
    last_opened_e: str | None = None

    @field_validator("last_opened_d", "last_opened_e")
    @classmethod
    def validate_final_opened(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_hex(v, "last_opened_d/e")


class MPCBatchAccumulateResponse(BaseModel):
    session_id: str
    purchase_idx: int
    accumulated: bool
    purchases_accumulated_so_far: int


class MPCBatchOpenRequest(BaseModel):
    """POST /v1/mpc/batch/open — After every purchase in the batch has
    been accumulated, the coordinator asks each peer for its final
    running sum share. Only this single scalar per peer is revealed;
    the coordinator reconstructs the total score change from the
    resulting t-of-N Shamir points.
    """

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")


class MPCBatchOpenResponse(BaseModel):
    session_id: str
    # The peer's accumulated sum-of-(Q_p(s_p) - c_0_p) share, hex-encoded.
    sum_share: str
    # Convenience echo so the coordinator can sanity-check.
    purchases_accumulated: int
    validator_x: int
    # Public c_0 register accumulated locally from the gain-vector
    # constant terms. Every peer computes this from the same public
    # inputs, so the coordinator can cross-check them for agreement
    # and is expected to see identical values.
    public_c_0_sum: str


# ---------------------------------------------------------------------------
# Share Info (for peer share discovery)
# ---------------------------------------------------------------------------


class ShareInfoResponse(BaseModel):
    """GET /v1/signal/{id}/share_info — Return share coordinates for MPC.

    Requires validator-signed request authentication.
    """

    signal_id: str
    share_x: int
    shamir_threshold: int = 7


# ---------------------------------------------------------------------------
# OT Network Endpoints (distributed triple generation)
# ---------------------------------------------------------------------------


class OTSetupRequest(BaseModel):
    """POST /v1/mpc/ot/setup — Initialize distributed triple generation."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    n_triples: int = Field(ge=1, le=20)
    x_coords: list[int] = Field(max_length=20)
    threshold: int = Field(default=7, ge=1, le=20)
    # Optional field prime for test configurations (default: BN254 prime)
    field_prime: str | None = Field(default=None, max_length=66)
    # Optional DH group prime for test configurations (default: RFC 3526 Group 14)
    dh_prime: str | None = Field(default=None, max_length=1024)

    @field_validator("x_coords")
    @classmethod
    def validate_x_coords(cls, v: list[int]) -> list[int]:
        for x in v:
            if x < 1 or x > 255:
                raise ValueError(f"x_coords values must be 1-255, got {x}")
        return v


class OTSetupResponse(BaseModel):
    session_id: str
    accepted: bool
    sender_public_keys: dict[str, str] = Field(default_factory=dict)  # {triple_idx: hex_pk}


class OTChoicesRequest(BaseModel):
    """POST /v1/mpc/ot/choices — Exchange OT choice commitments."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    peer_sender_pks: dict[str, str] = Field(default_factory=dict)  # {triple_idx: hex_pk}
    # Choices are sent in a compact binary format: base64 of concatenated T_k values
    choices: dict[str, list[str]] = Field(default_factory=dict)  # {triple_idx: [hex_Tk]}


class OTChoicesResponse(BaseModel):
    session_id: str
    choices: dict[str, list[str]] = Field(default_factory=dict)  # {triple_idx: [hex_Tk]}


class OTTransfersRequest(BaseModel):
    """POST /v1/mpc/ot/transfers — Exchange encrypted OT messages."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    # Peer's choices for this party's sender instances
    peer_choices: dict[str, list[str]] = Field(default_factory=dict)  # {triple_idx: [hex_Tk]}


class OTTransfersResponse(BaseModel):
    session_id: str
    # Encrypted pairs: {triple_idx: [[hex_E0, hex_E1], ...]}
    transfers: dict[str, list[list[str]]] = Field(default_factory=dict)
    # Sender shares accumulated (hex-encoded): {triple_idx: hex}
    sender_shares: dict[str, str] = Field(default_factory=dict)


class OTCompleteRequest(BaseModel):
    """POST /v1/mpc/ot/complete — Finalize OT and compute Shamir evaluations."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    # Encrypted transfers from the peer's sender instances
    peer_transfers: dict[str, list[list[str]]] = Field(default_factory=dict)
    # Sender shares from this party's sender instances (hex-encoded)
    own_sender_shares: dict[str, str] = Field(default_factory=dict)


class OTCompleteResponse(BaseModel):
    session_id: str
    completed: bool


class OTSharesRequest(BaseModel):
    """GET /v1/mpc/ot/shares — Fetch Shamir evaluations for a party."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    party_x: int = Field(ge=1, le=255)


class OTSharesResponse(BaseModel):
    session_id: str
    # Partial triple shares: [{a: hex, b: hex, c: hex}, ...]
    triple_shares: list[dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Check-Odds (buyer-facing odds lookup via validator)
# ---------------------------------------------------------------------------


class CheckOddsRequest(BaseModel):
    """POST /v1/signal/{id}/check-odds -- Fetch current odds for BPA/WPA pricing.

    The validator fetches fresh odds for all lines from a miner,
    filters by the buyer's available sportsbooks, and returns
    BPA/WPA per line. The MPC then selects at the secret index.
    """

    buyer_address: str = Field(max_length=256)
    buyer_books: list[str] = Field(min_length=1, max_length=50)
    buyer_signature: str = Field(default="", max_length=2048)


class BookPrice(BaseModel):
    bookmaker: str = Field(max_length=64)
    odds: float


class LineOdds(BaseModel):
    index: int
    bpa: float = 0  # best price available from buyer's books at or above committed
    wpa: float = 0  # worst price at or above committed
    executable: bool = False  # at least one book offers this line at or above committed
    per_book: list[BookPrice] = Field(default_factory=list)


class CheckOddsResponse(BaseModel):
    signal_id: str
    line_count: int
    odds: list[LineOdds]
    bpa_mode: bool  # from the signal's on-chain setting
    source: str = "validator"


# ---------------------------------------------------------------------------
# Buyer Preferences
# ---------------------------------------------------------------------------


class SetPreferencesRequest(BaseModel):
    """PUT /v1/preferences/{address} -- Store buyer preferences."""

    books: list[str] = Field(min_length=0, max_length=50)
    encrypted_data: str = Field(default="", max_length=10000)
    signature: str = Field(default="", max_length=2048)


class PreferencesResponse(BaseModel):
    address: str
    books: list[str] = []
    encrypted_data: str = ""


# ---------------------------------------------------------------------------
# Circuit Breaker Appeal (CUSUM-flagged miners)
# ---------------------------------------------------------------------------


class CircuitBreakerStatusResponse(BaseModel):
    """GET /v1/cb/status/{hotkey} -- query a miner's CUSUM state.

    Miners can read this to know if they're flagged, what their current
    CUSUM score is, and which recent queries were the disputed ones
    (so they can construct an appeal proof). Returns null fields when
    no state exists for the hotkey.
    """

    hotkey: str
    score: float
    sample_count: int
    flagged: bool
    flagged_at: float
    last_disputes: list[tuple[str, float]]
    threshold: float


class CircuitBreakerAppealRequest(BaseModel):
    """POST /v1/cb/appeal -- a flagged miner submits proof to clear the flag.

    The miner submits the disputed query IDs they want to defend, the
    TLSNotary proof of their declared source returning the data they
    served, and the declared source URL. The validator verifies the
    proof and clears or denies the flag accordingly.

    Verification mode is gated by DJINN_FF_APPEAL_MECHANISM. When the
    flag is OFF, the endpoint returns 503. When the flag is ON but the
    underlying TLSNotary verifier is not yet wired, the endpoint runs
    in honor-system mode (appeal succeeds on hotkey signature alone)
    so the wire protocol can be tested before full TLSNotary
    integration lands. The mode is reflected in the response.
    """

    hotkey: str = Field(max_length=128)
    declared_source: str = Field(max_length=512)
    disputed_query_ids: list[str] = Field(min_length=1, max_length=200)
    tlsnotary_proof: str = Field(default="", max_length=131072)
    miner_signature: str = Field(default="", max_length=2048)


class CircuitBreakerAppealResponse(BaseModel):
    hotkey: str
    verdict: str  # "accepted", "denied", "honor_system_accepted", "not_flagged"
    cleared: bool
    new_score: float
    verification_mode: str  # "tlsnotary" or "honor_system" or "disabled"
    message: str = ""


# ---------------------------------------------------------------------------
# Canonical Odds (validator-served, decoupled from The Odds API)
# ---------------------------------------------------------------------------


class CanonicalOddsRequest(BaseModel):
    """POST /v1/odds/canonical -- fetch live odds in canonical form.

    The validator queries the miner network for the requested sport and
    market, returns one observation per (event, bookmaker, side) tuple
    in the canonical schema. Lets clients hit validators directly
    instead of bouncing through a centralized provider proxy.

    Gated by DJINN_FF_CANONICAL_ODDS while the adapter ecosystem
    matures. Old clients that hit /v1/check or /api/odds keep working
    unchanged.
    """

    sport: str = Field(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    market: str = Field(default="moneyline", max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    bookmakers: list[str] = Field(default_factory=list, max_length=50)
    event_id: str | None = Field(default=None, max_length=256)


class CanonicalOddsObservation(BaseModel):
    event_id: str
    sport: str
    home_team: str
    away_team: str
    commence_time_ms: int
    market: str
    side: str
    decimal_price: float
    line: float | None = None
    bookmaker: str
    fetched_at_ms: int
    source: str


class CanonicalOddsResponse(BaseModel):
    sport: str
    market: str
    requested_bookmakers: list[str]
    observations: list[CanonicalOddsObservation]
    miner_count: int
    served_at_ms: int
    feature_flag_enabled: bool


# ------------------------------------------------------------------
# Web Attestation (whitepaper S15 -- pure Bittensor, no Base chain)
# ------------------------------------------------------------------


_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9_\-.:]{1,256}$")


class AttestRequest(BaseModel):
    """POST /v1/attest — Request TLSNotary attestation of a web page."""

    url: str = Field(max_length=2048, description="HTTPS URL to attest")
    request_id: str = Field(max_length=256, description="Unique request ID for tracking")
    timeout: float | None = Field(
        None,
        ge=30,
        le=600,
        description="Max seconds to wait for proof. Overrides the default tier-based timeout (30-600s).",
    )
    min_memory_gb: float | None = Field(
        None,
        ge=0,
        le=1024,
        description="Minimum available RAM (GB) required on the miner. "
        "Large pages or API responses may need miners with 32GB+ RAM. "
        "When set, only miners reporting sufficient available memory are selected.",
    )

    @field_validator("url")
    @classmethod
    def validate_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("URL must use HTTPS")
        import ipaddress
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(v)
        if not parsed.hostname:
            raise ValueError("URL must have a valid hostname")
        hostname = parsed.hostname.lower()
        # Block localhost by name
        if hostname in ("localhost", "ip6-localhost", "ip6-loopback"):
            raise ValueError("URL must not point to private/internal addresses")
        # Check if hostname is an IP literal and block non-global addresses
        try:
            addr = ipaddress.ip_address(hostname)
        except ValueError:
            # Domain name — resolve to IP and check for private/internal addresses
            try:
                resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                for family, _, _, _, sockaddr in resolved:
                    ip_str = sockaddr[0]
                    addr = ipaddress.ip_address(ip_str)
                    if not addr.is_global:
                        raise ValueError("URL must not point to private/internal addresses")
            except socket.gaierror:
                pass  # DNS resolution failed — will fail at request time anyway
        else:
            if not addr.is_global:
                raise ValueError("URL must not point to private/internal addresses")
        return v

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, v: str) -> str:
        if not _REQUEST_ID_RE.match(v):
            raise ValueError("request_id must be 1-256 alphanumeric chars, hyphens, underscores, dots, or colons")
        return v


class NotarySessionResponse(BaseModel):
    """POST /v1/notary/session — Assigned notary miner for external provers."""

    session_id: str
    miner_ip: str
    miner_port: int
    miner_ws_path: str = "/v1/notary/ws"
    miner_hotkey: str
    notary_public_key: str
    expires_at: int
    # Reliability metadata so consumers can assess assignment quality
    miner_uid: int = -1
    tier: str = "unknown"  # "proven", "unproven", or "unknown"
    reliability_score: float = 0.0  # 0.0-1.0, composite notary reliability


class AttestResponse(BaseModel):
    """Response from web attestation proof generation and verification."""

    request_id: str
    url: str
    success: bool
    verified: bool = False
    proof_hex: str | None = Field(default=None, description="TLSNotary presentation bytes (hex)")
    response_body: str | None = Field(default=None, description="HTTP response body extracted from the verified proof")
    server_name: str | None = None
    timestamp: int = Field(default=0, description="Unix timestamp of attestation")
    miner_uid: int | None = Field(default=None, description="UID of the miner that generated the proof")
    notary_uid: int | None = Field(
        default=None, description="UID of the peer notary miner (None = centralized PSE notary)"
    )
    blocked: bool = Field(
        default=False, description="True if the site served a bot challenge/wall instead of actual content"
    )
    error: str | None = None
    busy: bool = False
    retry_after: int | None = Field(default=None, description="Seconds to wait before retrying")


# ---------------------------------------------------------------------------
# Masked polynomial set-membership MPC (mpc_membership)
# ---------------------------------------------------------------------------
#
# Wire protocol for the O(log k)-round set-membership check that replaces
# the O(k) sequential-gate protocol. Sibling of mpc_membership.py. Each
# endpoint corresponds to one round of distributed computation.


class MembershipInitRequest(BaseModel):
    """POST /v1/mpc/membership/init — start a membership session on a peer."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    signal_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    coordinator_x: int = Field(ge=1, le=255)
    participant_xs: list[int] = Field(max_length=20)
    threshold: int = Field(ge=1, le=20)
    available_indices: list[int] = Field(max_length=2000)
    # This peer's triple a/b/c share (hex-encoded), one entry per gate.
    # Total entries = n_power_gates + 1 (last triple used for mask multiply).
    triple_a: list[str] = Field(max_length=2048)
    triple_b: list[str] = Field(max_length=2048)
    triple_c: list[str] = Field(max_length=2048)
    # This peer's share of the random mask s (hex-encoded).
    mask_share: str

    @field_validator("available_indices")
    @classmethod
    def validate_indices(cls, v: list[int]) -> list[int]:
        for idx in v:
            if idx < 1 or idx > 2000:
                raise ValueError(f"available_indices values must be 1-2000, got {idx}")
        if not v:
            raise ValueError("available_indices must be non-empty")
        return v

    @field_validator("participant_xs")
    @classmethod
    def validate_participants(cls, v: list[int]) -> list[int]:
        for x in v:
            if x < 1 or x > 255:
                raise ValueError(f"participant_xs values must be 1-255, got {x}")
        if len(set(v)) != len(v):
            raise ValueError("participant_xs must not contain duplicates")
        return v


class MembershipInitResponse(BaseModel):
    session_id: str
    accepted: bool
    message: str = ""


class MembershipRoundOpModel(BaseModel):
    """One power-tree multiplication op in a round."""

    gate_idx: int = Field(ge=0, le=2047)
    a_pow: int = Field(ge=1, le=2000)
    b_pow: int = Field(ge=1, le=2000)


class MembershipOpenedPowerModel(BaseModel):
    """Publicly opened d, e from a completed power-tree multiplication."""

    gate_idx: int = Field(ge=0, le=2047)
    target_pow: int = Field(ge=2, le=2000)
    opened_d: str  # hex
    opened_e: str  # hex


class MembershipRoundRequest(BaseModel):
    """POST /v1/mpc/membership/round — compute one power-tree round.

    ``prev_opened`` carries the opened d, e from the previous round
    (empty for the first round). The peer first finalizes those into
    its ``power_shares`` dict, then computes (d, e) for the new ops.
    """

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    round_idx: int = Field(ge=0, le=20)
    ops: list[MembershipRoundOpModel] = Field(max_length=2048)
    prev_opened: list[MembershipOpenedPowerModel] = Field(
        default_factory=list,
        max_length=2048,
    )


class MembershipRoundOpShare(BaseModel):
    gate_idx: int = Field(ge=0, le=2047)
    d_share: str  # hex
    e_share: str  # hex


class MembershipRoundResponse(BaseModel):
    session_id: str
    round_idx: int
    op_shares: list[MembershipRoundOpShare]


class MembershipFinalizeMaskRequest(BaseModel):
    """POST /v1/mpc/membership/finalize_mask — compute [q] then (d, e) for [s*q]."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    final_opened: list[MembershipOpenedPowerModel] = Field(
        default_factory=list,
        max_length=2048,
    )
    # Non-empty: compute_q_share() reads coefficients[0] (the public constant).
    coefficients: list[str] = Field(min_length=1, max_length=2048)  # hex-encoded


class MembershipFinalizeMaskResponse(BaseModel):
    session_id: str
    mask_d_share: str  # hex
    mask_e_share: str  # hex


class MembershipRevealRequest(BaseModel):
    """POST /v1/mpc/membership/reveal — final share of [s*p(r)]."""

    session_id: str = Field(max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    mask_opened_d: str  # hex
    mask_opened_e: str  # hex


class MembershipRevealResponse(BaseModel):
    session_id: str
    product_share: str  # hex
