"""Tests for peer-to-peer notary discovery, pairing, and scoring."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from djinn_validator.core.challenges import (
    PeerNotary,
    _ws_handshake_ok,
    assign_peer_notary,
    discover_peer_notaries,
)
from djinn_validator.core.scoring import MinerMetrics, MinerScorer
from djinn_validator.core.tlsn import verify_proof


class TestPeerNotaryDiscovery:
    """Test discovery of notary-capable miners."""

    @pytest.mark.asyncio
    async def test_discover_notary_miners(self) -> None:
        """Miners with /v1/notary/info enabled AND working WebSocket are discovered."""
        axons = [
            {"uid": 1, "hotkey": "hk1", "ip": "10.0.0.1", "port": 8422},
            {"uid": 2, "hotkey": "hk2", "ip": "10.0.0.2", "port": 8422},
            {"uid": 3, "hotkey": "hk3", "ip": "10.0.0.3", "port": 8422},
        ]

        responses = {
            "http://10.0.0.1:8422/v1/notary/info": {
                "enabled": True,
                "pubkey_hex": "a" * 66,
                "port": 7047,
            },
            "http://10.0.0.2:8422/v1/notary/info": {
                "enabled": False,
                "pubkey_hex": "",
                "port": 0,
            },
            # Miner 3 returns 404 (old miner without endpoint)
        }

        async def mock_get(url: str, **kwargs):
            resp = MagicMock()
            if url in responses:
                resp.status_code = 200
                resp.json.return_value = responses[url]
            else:
                resp.status_code = 404
            return resp

        client = MagicMock()
        client.get = mock_get

        with patch(
            "djinn_validator.core.challenges._ws_handshake_ok",
            return_value=True,
        ):
            notaries = await discover_peer_notaries(client, axons)

        assert len(notaries) == 1
        assert notaries[0].uid == 1
        assert notaries[0].pubkey_hex == "a" * 66
        assert notaries[0].notary_port == 7047

    @pytest.mark.asyncio
    async def test_discover_excludes_broken_websocket(self) -> None:
        """Miners with HTTP 200 but broken WebSocket are excluded."""
        axons = [
            {"uid": 1, "hotkey": "hk1", "ip": "10.0.0.1", "port": 8422},
        ]

        async def mock_get(url: str, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "enabled": True,
                "pubkey_hex": "a" * 66,
                "port": 7047,
            }
            return resp

        client = MagicMock()
        client.get = mock_get

        # WebSocket probe fails (returns 403 or connection refused)
        with patch(
            "djinn_validator.core.challenges._ws_handshake_ok",
            return_value=False,
        ):
            notaries = await discover_peer_notaries(client, axons)

        assert len(notaries) == 0

    @pytest.mark.asyncio
    async def test_discover_handles_timeout(self) -> None:
        """Timeout during probe is handled gracefully."""
        import httpx

        axons = [{"uid": 1, "hotkey": "hk1", "ip": "10.0.0.1", "port": 8422}]

        async def mock_get(url: str, **kwargs):
            raise httpx.ConnectTimeout("timed out")

        client = MagicMock()
        client.get = mock_get

        notaries = await discover_peer_notaries(client, axons)
        assert len(notaries) == 0

    @pytest.mark.asyncio
    async def test_discover_skips_no_ip(self) -> None:
        """Miners without IP are skipped."""
        axons = [{"uid": 1, "hotkey": "hk1", "ip": "", "port": 0}]
        client = MagicMock()
        notaries = await discover_peer_notaries(client, axons)
        assert len(notaries) == 0


class TestPeerNotaryAssignment:
    """Test random notary pairing."""

    def test_assign_excludes_self(self) -> None:
        """Prover is never assigned as its own notary."""
        notaries = [
            PeerNotary(uid=1, ip="10.0.0.1", port=8422, notary_port=7047, pubkey_hex="a" * 66),
            PeerNotary(uid=2, ip="10.0.0.2", port=8422, notary_port=7047, pubkey_hex="b" * 66),
        ]
        # Assign for uid=1 should never return uid=1
        for _ in range(50):
            assigned = assign_peer_notary(1, notaries)
            assert assigned is not None
            assert assigned.uid != 1

    def test_assign_returns_none_when_only_self(self) -> None:
        """Returns None if the only notary is the prover itself."""
        notaries = [
            PeerNotary(uid=1, ip="10.0.0.1", port=8422, notary_port=7047, pubkey_hex="a" * 66),
        ]
        assert assign_peer_notary(1, notaries) is None

    def test_assign_returns_none_when_empty(self) -> None:
        assert assign_peer_notary(1, []) is None

    def test_assign_excludes_same_ip(self) -> None:
        """Notaries on the same IP as the prover are excluded (same operator)."""
        notaries = [
            PeerNotary(uid=1, ip="10.0.0.1", port=8422, notary_port=7047, pubkey_hex="a" * 66),
            PeerNotary(uid=2, ip="10.0.0.1", port=8423, notary_port=7047, pubkey_hex="b" * 66),
            PeerNotary(uid=3, ip="10.0.0.2", port=8422, notary_port=7047, pubkey_hex="c" * 66),
        ]
        # uid=1 on 10.0.0.1 should never get uid=2 (same IP)
        for _ in range(50):
            assigned = assign_peer_notary(1, notaries, prover_ip="10.0.0.1")
            assert assigned is not None
            assert assigned.uid == 3  # only eligible notary

    def test_assign_returns_none_when_all_same_ip(self) -> None:
        """Returns None if all notaries share the prover's IP."""
        notaries = [
            PeerNotary(uid=1, ip="10.0.0.1", port=8422, notary_port=7047, pubkey_hex="a" * 66),
            PeerNotary(uid=2, ip="10.0.0.1", port=8423, notary_port=7047, pubkey_hex="b" * 66),
        ]
        assert assign_peer_notary(1, notaries, prover_ip="10.0.0.1") is None

    def test_assign_excludes_same_coldkey(self) -> None:
        """Sybil cluster: 30 UIDs across distinct IPs but one coldkey can't self-notarize.

        Same-coldkey self-notarization is not real adversarial verification and
        double-rewards Sybil clusters (miner credit + notary credit for the same
        crypto work). The IP filter alone is bypassed by spreading across cloud
        regions; coldkey filter closes that gap.
        """
        sybil_ck = "5HYtaxnfHxxn2UoRnf" + "a" * 30
        honest_ck = "5GQgRvkUazWv2zGJFF" + "b" * 30
        notaries = [
            PeerNotary(uid=1, ip="10.0.0.1", port=8422, notary_port=7047, pubkey_hex="a" * 66, coldkey=sybil_ck),
            PeerNotary(uid=2, ip="10.0.0.2", port=8422, notary_port=7047, pubkey_hex="b" * 66, coldkey=sybil_ck),
            PeerNotary(uid=3, ip="10.0.0.3", port=8422, notary_port=7047, pubkey_hex="c" * 66, coldkey=honest_ck),
        ]
        # uid=1 (sybil) on its own IP: must never get uid=2 (same coldkey, different IP)
        for _ in range(50):
            assigned = assign_peer_notary(
                1,
                notaries,
                prover_ip="10.0.0.1",
                prover_coldkey=sybil_ck,
            )
            assert assigned is not None
            assert assigned.uid == 3, "must pick honest notary, not same-coldkey peer"

    def test_assign_returns_none_when_all_same_coldkey(self) -> None:
        """Returns None if every notary shares the prover's coldkey."""
        ck = "5HYtaxnfHxxn2UoRnf" + "a" * 30
        notaries = [
            PeerNotary(uid=1, ip="10.0.0.1", port=8422, notary_port=7047, pubkey_hex="a" * 66, coldkey=ck),
            PeerNotary(uid=2, ip="10.0.0.2", port=8422, notary_port=7047, pubkey_hex="b" * 66, coldkey=ck),
        ]
        assert assign_peer_notary(1, notaries, prover_coldkey=ck) is None

    def test_assign_coldkey_filter_skips_when_notary_coldkey_unknown(self) -> None:
        """Notaries with empty coldkey are not filtered (backwards-compat for old discovery)."""
        notaries = [
            PeerNotary(uid=2, ip="10.0.0.2", port=8422, notary_port=7047, pubkey_hex="b" * 66, coldkey=""),
        ]
        # Even with prover_coldkey set, an unknown-coldkey notary stays eligible
        assigned = assign_peer_notary(1, notaries, prover_coldkey="some-ck")
        assert assigned is not None and assigned.uid == 2

    def test_assign_random_distribution(self) -> None:
        """Assignments are distributed across eligible notaries."""
        notaries = [
            PeerNotary(uid=i, ip=f"10.0.0.{i}", port=8422, notary_port=7047, pubkey_hex=f"{i:066d}")
            for i in range(1, 6)
        ]
        counts: dict[int, int] = {i: 0 for i in range(1, 6)}
        for _ in range(500):
            assigned = assign_peer_notary(1, notaries)
            if assigned:
                counts[assigned.uid] += 1

        # uid=1 should never be assigned
        assert counts[1] == 0
        # Each other uid should get some assignments
        for uid in range(2, 6):
            assert counts[uid] > 50  # ~125 expected each


class TestNotaryScoring:
    """Test notary reliability scoring and bonus."""

    def test_notary_reliability_no_duties(self) -> None:
        m = MinerMetrics(uid=1, hotkey="hk1")
        assert m.notary_reliability() == 0.0

    def test_notary_reliability_all_successful(self) -> None:
        m = MinerMetrics(uid=1, hotkey="hk1")
        for _ in range(5):
            m.record_notary_duty(proof_valid=True)
        assert m.notary_reliability() == 1.0

    def test_notary_reliability_partial(self) -> None:
        m = MinerMetrics(uid=1, hotkey="hk1")
        m.record_notary_duty(proof_valid=True)
        m.record_notary_duty(proof_valid=False)
        assert m.notary_reliability() == 0.5

    def test_notary_bonus_in_sports_scores(self) -> None:
        """Miners with perfect notary reliability get a 10% uptime bonus."""
        scorer = MinerScorer()

        # Miner 1: perfect notary, 100% uptime
        m1 = scorer.get_or_create(1, "hk1")
        m1.record_query(correct=True, latency=0.5, proof_submitted=True)
        m1.record_health_check(responded=True)
        for _ in range(5):
            m1.record_notary_duty(proof_valid=True)

        # Miner 2: no notary service, same stats otherwise
        m2 = scorer.get_or_create(2, "hk2")
        m2.record_query(correct=True, latency=0.5, proof_submitted=True)
        m2.record_health_check(responded=True)

        weights = scorer.compute_weights(is_active_epoch=True)

        # Miner 1 should have a slightly higher weight due to notary bonus
        assert weights[1] > weights[2]

    def test_epoch_reset_clears_notary_metrics(self) -> None:
        scorer = MinerScorer()
        m = scorer.get_or_create(1, "hk1")
        m.record_notary_duty(proof_valid=True)
        m.record_health_check(responded=True)
        assert m.notary_duties_assigned == 1

        scorer.reset_epoch()
        assert m.notary_duties_assigned == 0
        assert m.notary_duties_completed == 0

    def test_lifetime_notary_duties_survive_epoch_reset(self) -> None:
        """Lifetime notary counters accumulate across epochs; per-epoch counters reset.

        Regression: v1166 folded notary_duties_assigned (per-epoch) into
        total_scored_samples(), which is exactly the pattern fixed in
        commit 1c62061 for queries_total. A miner with 200 lifetime duties
        but 0 this epoch must NOT drop back into bootstrap every tempo.
        """
        scorer = MinerScorer()
        m = scorer.get_or_create(1, "hk1")
        for _ in range(10):
            m.record_notary_duty(proof_valid=True)
        m.record_health_check(responded=True)

        assert m.notary_duties_assigned == 10
        assert m.lifetime_notary_duties_assigned == 10
        assert m.lifetime_notary_duties_completed == 10
        # total_scored_samples reflects lifetime notary work
        assert m.total_scored_samples() == 10

        scorer.reset_epoch()

        # Per-epoch counters cleared
        assert m.notary_duties_assigned == 0
        assert m.notary_duties_completed == 0
        # Lifetime counters preserved
        assert m.lifetime_notary_duties_assigned == 10
        assert m.lifetime_notary_duties_completed == 10
        # CRITICAL: total_scored_samples stays non-zero across epochs
        assert m.total_scored_samples() == 10

    def test_record_notary_duty_increments_lifetime_on_failure(self) -> None:
        """Lifetime assigned counts all duties; completed only counts valid proofs."""
        m = MinerMetrics(uid=1, hotkey="hk1")
        m.record_notary_duty(proof_valid=True)
        m.record_notary_duty(proof_valid=False)
        m.record_notary_duty(proof_valid=True)

        assert m.lifetime_notary_duties_assigned == 3
        assert m.lifetime_notary_duties_completed == 2

    def test_record_notary_duty_accumulates_work_on_success(self) -> None:
        """lifetime_notary_proof_bytes and _duration_ms accumulate only on valid proofs.

        Instrumentation for DJINN_FF_PROOF_COMPLEXITY_WEIGHT: the per-session
        work-done signal lets a future scoring change reward notaries serving
        heavier TLSN sessions sub-linearly. Failed duties don't represent real
        work, so they must not contribute to the byte/duration totals.
        """
        m = MinerMetrics(uid=1, hotkey="hk1")
        m.record_notary_duty(proof_valid=True, proof_bytes=10_000, duration_ms=30_000)
        m.record_notary_duty(proof_valid=True, proof_bytes=50_000, duration_ms=90_000)
        assert m.lifetime_notary_proof_bytes == 60_000
        assert m.lifetime_notary_duration_ms == 120_000

        # Failed duty: assigned count goes up, completed + work totals unchanged
        m.record_notary_duty(proof_valid=False, proof_bytes=999_999, duration_ms=999_999)
        assert m.lifetime_notary_duties_assigned == 3
        assert m.lifetime_notary_duties_completed == 2
        assert m.lifetime_notary_proof_bytes == 60_000
        assert m.lifetime_notary_duration_ms == 120_000

    def test_record_notary_duty_defaults_zero(self) -> None:
        """Call sites that don't have byte/duration info (e.g. older attest
        code paths that only pass proof_valid) must not crash and must leave
        the work totals at zero on success."""
        m = MinerMetrics(uid=1, hotkey="hk1")
        m.record_notary_duty(proof_valid=True)
        assert m.lifetime_notary_duties_completed == 1
        assert m.lifetime_notary_proof_bytes == 0
        assert m.lifetime_notary_duration_ms == 0

    def test_notary_work_survives_epoch_reset(self) -> None:
        """Lifetime work totals survive scorer.reset_epoch(), same guarantee
        as lifetime_notary_duties_assigned. Prevents the v1170-class bug
        where folding a resettable counter into scoring makes the signal
        collapse every 12s."""
        scorer = MinerScorer()
        m = scorer.get_or_create(1, "hk1")
        m.record_notary_duty(proof_valid=True, proof_bytes=5_000, duration_ms=20_000)
        m.record_notary_duty(proof_valid=True, proof_bytes=7_000, duration_ms=25_000)

        scorer.reset_epoch()

        assert m.lifetime_notary_proof_bytes == 12_000
        assert m.lifetime_notary_duration_ms == 45_000


class TestPeerNotaryVerification:
    """Test that peer notary keys are accepted during proof verification."""

    @pytest.mark.asyncio
    async def test_verify_with_peer_notary_key(self) -> None:
        """Proof signed by a peer notary key is accepted."""
        peer_key = "a" * 66
        verified_output = json.dumps(
            {
                "status": "verified",
                "server_name": "example.com",
                "connection_time": "2026-03-01T00:00:00Z",
                "response_body": "hello",
                "notary_key": peer_key,
            }
        ).encode()

        async def mock_subprocess(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 0

            async def communicate():
                return verified_output, b""

            proc.communicate = communicate
            return proc

        with patch(
            "djinn_validator.core.tlsn.asyncio.create_subprocess_exec",
            side_effect=mock_subprocess,
        ):
            result = await verify_proof(
                b"fake_proof",
                expected_notary_key=peer_key,
            )

        assert result.verified is True

    @pytest.mark.asyncio
    async def test_verify_without_peer_key_uses_trusted(self) -> None:
        """Without expected_notary_key, falls back to TRUSTED_NOTARY_KEYS."""
        verified_output = json.dumps(
            {
                "status": "verified",
                "server_name": "example.com",
                "response_body": "hi",
            }
        ).encode()

        async def mock_subprocess(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 0

            async def communicate():
                return verified_output, b""

            proc.communicate = communicate
            return proc

        with patch(
            "djinn_validator.core.tlsn.asyncio.create_subprocess_exec",
            side_effect=mock_subprocess,
        ):
            # No TRUSTED_NOTARY_KEYS set and no peer key = dev mode (any key accepted)
            result = await verify_proof(b"fake_proof")

        assert result.verified is True


class TestBackwardsCompatibility:
    """Test that old miners/validators work with the new protocol."""

    def test_attest_payload_without_notary_fields(self) -> None:
        """Old validators send attestation payloads without notary_host/port.

        The validator's challenge code builds the payload dict — when no peer
        notary is assigned, notary_host/notary_port are omitted. Old miners
        that don't understand these fields ignore extra JSON keys (Pydantic
        ignores unknown fields by default).
        """
        # Simulate old-style payload (no notary fields)
        old_payload = {"url": "https://example.com", "request_id": "test-123"}
        assert "notary_host" not in old_payload
        assert "notary_port" not in old_payload

        # Simulate new-style payload (with notary fields)
        new_payload = {
            "url": "https://example.com",
            "request_id": "test-456",
            "notary_host": "10.0.0.5",
            "notary_port": 7047,
        }
        assert new_payload["notary_host"] == "10.0.0.5"
        assert new_payload["notary_port"] == 7047

    @pytest.mark.asyncio
    async def test_discover_skips_old_miners_without_endpoint(self) -> None:
        """Old miners without /v1/notary/info return 404 and are skipped."""
        axons = [{"uid": 1, "hotkey": "hk1", "ip": "10.0.0.1", "port": 8422}]

        async def mock_get(url: str, **kwargs):
            resp = MagicMock()
            resp.status_code = 404  # Old miner
            return resp

        client = MagicMock()
        client.get = mock_get

        notaries = await discover_peer_notaries(client, axons)
        assert len(notaries) == 0
