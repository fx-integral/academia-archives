"""Tests for the network-aware DH-based OT protocol.

Tests cover:
1. DH-based Gilboa OT correctness (sender/receiver halves)
2. Two-party triple generation (local simulation)
3. OTTripleGenState lifecycle
4. Serialization/deserialization of OT messages
5. API endpoint integration (share_info + OT endpoints)

Uses DH_GROUP_TEST (small safe prime p=1223) for fast tests.
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from djinn_validator.core.ot_network import (
    DH_GROUP_TEST,
    DHGroup,
    GilboaReceiverSetup,
    GilboaSenderSetup,
    OTTripleGenState,
    TwoPartyTripleResult,
    create_shamir_polynomial,
    deserialize_choices,
    deserialize_dh_public_key,
    deserialize_transfers,
    evaluate_polynomial,
    generate_two_party_triple_local,
    serialize_choices,
    serialize_dh_public_key,
    serialize_transfers,
    verify_two_party_triple,
)
from djinn_validator.utils.crypto import BN254_PRIME, Share

# Small field prime for fast tests
SMALL_PRIME = 104729  # 17-bit prime

# Use the test DH group for ALL tests (p=1223, instant exponentiations)
TEST_DH = DH_GROUP_TEST


# ---------------------------------------------------------------------------
# Gilboa OT unit tests
# ---------------------------------------------------------------------------


class TestGilboaDHOT:
    """Test the DH-based Gilboa OT multiplication."""

    def test_basic_multiplication(self) -> None:
        """sender_share + receiver_share == x * y mod p."""
        x, y = 42, 17
        sender = GilboaSenderSetup(x=x, prime=SMALL_PRIME, dh_group=TEST_DH)
        receiver = GilboaReceiverSetup(y=y, prime=SMALL_PRIME, dh_group=TEST_DH)

        choices = receiver.generate_choices(sender.get_public_key())
        pairs, sender_share = sender.process_choices(choices)
        receiver_share = receiver.decrypt_transfers(pairs)

        assert (sender_share + receiver_share) % SMALL_PRIME == (x * y) % SMALL_PRIME

    def test_zero_inputs(self) -> None:
        """x=0 or y=0 should give product 0."""
        for x, y in [(0, 100), (100, 0), (0, 0)]:
            sender = GilboaSenderSetup(x=x, prime=SMALL_PRIME, dh_group=TEST_DH)
            receiver = GilboaReceiverSetup(y=y, prime=SMALL_PRIME, dh_group=TEST_DH)
            choices = receiver.generate_choices(sender.get_public_key())
            pairs, s = sender.process_choices(choices)
            r = receiver.decrypt_transfers(pairs)
            assert (s + r) % SMALL_PRIME == 0

    def test_identity(self) -> None:
        """x * 1 == x."""
        x = 12345
        sender = GilboaSenderSetup(x=x, prime=SMALL_PRIME, dh_group=TEST_DH)
        receiver = GilboaReceiverSetup(y=1, prime=SMALL_PRIME, dh_group=TEST_DH)
        choices = receiver.generate_choices(sender.get_public_key())
        pairs, s = sender.process_choices(choices)
        r = receiver.decrypt_transfers(pairs)
        assert (s + r) % SMALL_PRIME == x % SMALL_PRIME

    def test_large_values(self) -> None:
        """Test with values near the field prime."""
        x = SMALL_PRIME - 1
        y = SMALL_PRIME - 2
        sender = GilboaSenderSetup(x=x, prime=SMALL_PRIME, dh_group=TEST_DH)
        receiver = GilboaReceiverSetup(y=y, prime=SMALL_PRIME, dh_group=TEST_DH)
        choices = receiver.generate_choices(sender.get_public_key())
        pairs, s = sender.process_choices(choices)
        r = receiver.decrypt_transfers(pairs)
        assert (s + r) % SMALL_PRIME == (x * y) % SMALL_PRIME

    def test_randomized(self) -> None:
        """5 random multiplications should all verify."""
        for _ in range(5):
            x = secrets.randbelow(SMALL_PRIME)
            y = secrets.randbelow(SMALL_PRIME)
            sender = GilboaSenderSetup(x=x, prime=SMALL_PRIME, dh_group=TEST_DH)
            receiver = GilboaReceiverSetup(y=y, prime=SMALL_PRIME, dh_group=TEST_DH)
            choices = receiver.generate_choices(sender.get_public_key())
            pairs, s = sender.process_choices(choices)
            r = receiver.decrypt_transfers(pairs)
            assert (s + r) % SMALL_PRIME == (x * y) % SMALL_PRIME

    def test_shares_are_random(self) -> None:
        """Running the same multiplication twice should give different shares."""
        x, y = 100, 200
        sender1 = GilboaSenderSetup(x=x, prime=SMALL_PRIME, dh_group=TEST_DH)
        receiver1 = GilboaReceiverSetup(y=y, prime=SMALL_PRIME, dh_group=TEST_DH)
        choices1 = receiver1.generate_choices(sender1.get_public_key())
        pairs1, s1 = sender1.process_choices(choices1)
        r1 = receiver1.decrypt_transfers(pairs1)

        sender2 = GilboaSenderSetup(x=x, prime=SMALL_PRIME, dh_group=TEST_DH)
        receiver2 = GilboaReceiverSetup(y=y, prime=SMALL_PRIME, dh_group=TEST_DH)
        choices2 = receiver2.generate_choices(sender2.get_public_key())
        pairs2, s2 = sender2.process_choices(choices2)
        r2 = receiver2.decrypt_transfers(pairs2)

        # Same product, different shares
        assert (s1 + r1) % SMALL_PRIME == (s2 + r2) % SMALL_PRIME
        assert s1 != s2 or r1 != r2  # Extremely unlikely to be equal

    def test_dh_public_key_in_group(self) -> None:
        """DH public keys should be in the MODP group."""
        sender = GilboaSenderSetup(x=1, prime=SMALL_PRIME, dh_group=TEST_DH)
        pk = sender.get_public_key()
        assert 1 < pk < TEST_DH.prime

    def test_n_bits_matches_field(self) -> None:
        """Number of OT bits matches field prime bit length."""
        sender = GilboaSenderSetup(x=1, prime=SMALL_PRIME, dh_group=TEST_DH)
        assert sender._n_bits == SMALL_PRIME.bit_length()

    def test_choice_count(self) -> None:
        """Receiver generates exactly n_bits choices."""
        receiver = GilboaReceiverSetup(y=42, prime=SMALL_PRIME, dh_group=TEST_DH)
        sender = GilboaSenderSetup(x=1, prime=SMALL_PRIME, dh_group=TEST_DH)
        choices = receiver.generate_choices(sender.get_public_key())
        assert len(choices) == SMALL_PRIME.bit_length()


# ---------------------------------------------------------------------------
# Two-party triple generation tests
# ---------------------------------------------------------------------------


class TestTwoPartyTriple:
    """Test the 2-party distributed triple generation."""

    def test_triple_verifies(self) -> None:
        """A generated triple should satisfy a*b == c."""
        t = generate_two_party_triple_local(prime=SMALL_PRIME, dh_group=TEST_DH)
        assert verify_two_party_triple(t, prime=SMALL_PRIME)

    def test_triple_randomness(self) -> None:
        """Two triples should have different values."""
        t1 = generate_two_party_triple_local(prime=SMALL_PRIME, dh_group=TEST_DH)
        t2 = generate_two_party_triple_local(prime=SMALL_PRIME, dh_group=TEST_DH)
        assert t1.a0 != t2.a0 or t1.b0 != t2.b0

    def test_additive_shares(self) -> None:
        """Additive shares should combine correctly."""
        t = generate_two_party_triple_local(prime=SMALL_PRIME, dh_group=TEST_DH)
        a = (t.a0 + t.a1) % SMALL_PRIME
        b = (t.b0 + t.b1) % SMALL_PRIME
        c = (t.c0 + t.c1) % SMALL_PRIME
        assert c == (a * b) % SMALL_PRIME

    def test_multiple_triples(self) -> None:
        """Generate and verify 3 triples."""
        for _ in range(3):
            t = generate_two_party_triple_local(prime=SMALL_PRIME, dh_group=TEST_DH)
            assert verify_two_party_triple(t, prime=SMALL_PRIME)


# ---------------------------------------------------------------------------
# OTTripleGenState lifecycle tests
# ---------------------------------------------------------------------------


class TestOTTripleGenState:
    """Test the per-party state management for distributed triple gen."""

    def _make_state(
        self,
        role: str = "coordinator",
        n_triples: int = 2,
    ) -> OTTripleGenState:
        return OTTripleGenState(
            session_id="test-session",
            party_role=role,
            n_triples=n_triples,
            x_coords=[1, 2, 3],
            threshold=2,
            prime=SMALL_PRIME,
            dh_group=TEST_DH,
        )

    def test_initialize(self) -> None:
        """State initialization generates correct number of values."""
        state = self._make_state()
        state.initialize()
        assert len(state.a_values) == 2
        assert len(state.b_values) == 2
        assert len(state.c_values) == 2
        assert len(state.senders) == 2
        assert len(state.receivers) == 2

    def test_sender_public_keys(self) -> None:
        """Get DH public keys for sender instances."""
        state = self._make_state()
        state.initialize()
        pks = state.get_sender_public_keys()
        assert len(pks) == 2
        for t, pk in pks.items():
            assert 1 < pk < TEST_DH.prime

    def test_full_two_party_lifecycle(self) -> None:
        """Run the full 2-party OT lifecycle locally between two states."""
        coord = self._make_state(role="coordinator", n_triples=1)
        peer = self._make_state(role="peer", n_triples=1)
        coord.initialize()
        peer.initialize()

        # Direction 1: coord is sender, peer is receiver
        coord_sender_pks = coord.get_sender_public_keys()
        peer_choices = peer.generate_receiver_choices(coord_sender_pks)
        coord_transfers, coord_sender_shares = coord.process_sender_choices(peer_choices)
        peer_receiver_shares = peer.decrypt_receiver_transfers(coord_transfers)

        # Direction 2: peer is sender, coord is receiver
        peer_sender_pks = peer.get_sender_public_keys()
        coord_choices = coord.generate_receiver_choices(peer_sender_pks)
        peer_transfers, peer_sender_shares = peer.process_sender_choices(coord_choices)
        coord_receiver_shares = coord.decrypt_receiver_transfers(peer_transfers)

        # Accumulate shares
        coord.accumulate_ot_shares(coord_sender_shares, coord_receiver_shares)
        peer.accumulate_ot_shares(peer_sender_shares, peer_receiver_shares)

        # Verify: c0 + c1 == (a0+a1) * (b0+b1) mod p
        for t in range(1):
            a = (coord.a_values[t] + peer.a_values[t]) % SMALL_PRIME
            b = (coord.b_values[t] + peer.b_values[t]) % SMALL_PRIME
            c = (coord.c_values[t] + peer.c_values[t]) % SMALL_PRIME
            assert c == (a * b) % SMALL_PRIME

    def test_shamir_evaluation(self) -> None:
        """Shamir polynomial evaluations are generated and accessible."""
        state = self._make_state()
        state.initialize()
        state.compute_shamir_evaluations()
        assert state.completed

        shares = state.get_shamir_shares_for_party(1)
        assert shares is not None
        assert len(shares) == 2
        for ts in shares:
            assert "a" in ts
            assert "b" in ts
            assert "c" in ts

    def test_combined_shamir_shares(self) -> None:
        """Combined Shamir evaluations from both parties reconstruct correct secret."""
        from djinn_validator.utils.crypto import reconstruct_secret

        coord = self._make_state(role="coordinator", n_triples=1)
        peer = self._make_state(role="peer", n_triples=1)
        coord.initialize()
        peer.initialize()

        # Run OT
        coord_sender_pks = coord.get_sender_public_keys()
        peer_choices = peer.generate_receiver_choices(coord_sender_pks)
        coord_transfers, coord_sender_shares = coord.process_sender_choices(peer_choices)
        peer_receiver_shares = peer.decrypt_receiver_transfers(coord_transfers)

        peer_sender_pks = peer.get_sender_public_keys()
        coord_choices = coord.generate_receiver_choices(peer_sender_pks)
        peer_transfers, peer_sender_shares = peer.process_sender_choices(coord_choices)
        coord_receiver_shares = coord.decrypt_receiver_transfers(peer_transfers)

        coord.accumulate_ot_shares(coord_sender_shares, coord_receiver_shares)
        peer.accumulate_ot_shares(peer_sender_shares, peer_receiver_shares)

        # Generate Shamir evaluations
        coord.compute_shamir_evaluations()
        peer.compute_shamir_evaluations()

        # Combine for each x-coordinate
        combined_a_shares = []
        combined_b_shares = []
        combined_c_shares = []
        for x in [1, 2, 3]:
            coord_shares = coord.get_shamir_shares_for_party(x)
            peer_shares = peer.get_shamir_shares_for_party(x)
            assert coord_shares is not None
            assert peer_shares is not None
            combined_a = (coord_shares[0]["a"] + peer_shares[0]["a"]) % SMALL_PRIME
            combined_b = (coord_shares[0]["b"] + peer_shares[0]["b"]) % SMALL_PRIME
            combined_c = (coord_shares[0]["c"] + peer_shares[0]["c"]) % SMALL_PRIME
            combined_a_shares.append(Share(x=x, y=combined_a))
            combined_b_shares.append(Share(x=x, y=combined_b))
            combined_c_shares.append(Share(x=x, y=combined_c))

        # Reconstruct secrets
        a = reconstruct_secret(combined_a_shares, SMALL_PRIME)
        b = reconstruct_secret(combined_b_shares, SMALL_PRIME)
        c = reconstruct_secret(combined_c_shares, SMALL_PRIME)
        assert c == (a * b) % SMALL_PRIME

    def test_not_completed_returns_none(self) -> None:
        """get_shamir_shares_for_party returns None before completion."""
        state = self._make_state()
        state.initialize()
        assert state.get_shamir_shares_for_party(1) is None


# ---------------------------------------------------------------------------
# Background-init timeout tests
# ---------------------------------------------------------------------------


class TestReceiverInitTimeout:
    """Regression: if the background _g_r_bases modexp thread doesn't
    finish in time, `_ensure_receivers_ready` must raise a typed exception
    instead of silently continuing (which previously surfaced as an opaque
    IndexError from generate_choices → 500 at the HTTP layer)."""

    def test_timeout_raises_typed_error(self) -> None:
        from djinn_validator.core.ot_network import OTReceiverNotReadyError

        # Construct without calling initialize() so no background thread
        # ever starts. _receivers_ready defaults to False and
        # _receiver_init_thread is unset, so the timeout path fires cleanly.
        state = OTTripleGenState(
            session_id="timeout-test",
            party_role="peer",
            n_triples=1,
            x_coords=[1, 2, 3],
            threshold=2,
            prime=SMALL_PRIME,
            dh_group=TEST_DH,
        )
        assert state._receivers_ready is False

        with pytest.raises(OTReceiverNotReadyError):
            state._ensure_receivers_ready()

    def test_generate_receiver_choices_propagates_timeout(self) -> None:
        from djinn_validator.core.ot_network import OTReceiverNotReadyError

        coord = OTTripleGenState(
            session_id="timeout-propagate",
            party_role="coordinator",
            n_triples=1,
            x_coords=[1, 2, 3],
            threshold=2,
            prime=SMALL_PRIME,
            dh_group=TEST_DH,
        )
        peer = OTTripleGenState(
            session_id="timeout-propagate",
            party_role="peer",
            n_triples=1,
            x_coords=[1, 2, 3],
            threshold=2,
            prime=SMALL_PRIME,
            dh_group=TEST_DH,
        )
        coord.initialize()
        peer.initialize()

        # Drain the fast background thread, then force the not-ready state.
        # Without the join there's a micro-race where the thread could set
        # _receivers_ready=True AFTER our assignment below.
        if peer._receiver_init_thread is not None:
            peer._receiver_init_thread.join(timeout=5)
        peer._receivers_ready = False
        peer._receiver_init_thread = None

        coord_sender_pks = coord.get_sender_public_keys()
        with pytest.raises(OTReceiverNotReadyError):
            peer.generate_receiver_choices(coord_sender_pks)


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------


class TestSerialization:
    """Test OT message serialization/deserialization."""

    def test_dh_public_key_roundtrip(self) -> None:
        pk = pow(TEST_DH.generator, 42, TEST_DH.prime)
        serialized = serialize_dh_public_key(pk, TEST_DH)
        deserialized = deserialize_dh_public_key(serialized)
        assert deserialized == pk

    def test_choices_roundtrip(self) -> None:
        values = [secrets.randbelow(TEST_DH.prime) for _ in range(10)]
        serialized = serialize_choices(values, TEST_DH)
        deserialized = deserialize_choices(serialized)
        assert deserialized == values

    def test_transfers_roundtrip(self) -> None:
        pairs = [(secrets.token_bytes(32), secrets.token_bytes(32)) for _ in range(10)]
        serialized = serialize_transfers(pairs)
        deserialized = deserialize_transfers(serialized)
        assert deserialized == pairs


# ---------------------------------------------------------------------------
# Polynomial helper tests
# ---------------------------------------------------------------------------


class TestPolynomial:
    """Test Shamir polynomial helpers."""

    def test_constant_polynomial(self) -> None:
        coeffs = [42]
        assert evaluate_polynomial(coeffs, 1, SMALL_PRIME) == 42
        assert evaluate_polynomial(coeffs, 99, SMALL_PRIME) == 42

    def test_linear_polynomial(self) -> None:
        coeffs = [5, 3]
        assert evaluate_polynomial(coeffs, 2, SMALL_PRIME) == 11

    def test_create_and_evaluate(self) -> None:
        poly = create_shamir_polynomial(42, 3, SMALL_PRIME)
        assert len(poly) == 4
        assert evaluate_polynomial(poly, 0, SMALL_PRIME) == 42


# ---------------------------------------------------------------------------
# API endpoint integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def test_app() -> TestClient:
    """Create a test app with a share store containing a test signal."""
    from djinn_validator.api.server import create_app
    from djinn_validator.core.mpc_coordinator import MPCCoordinator
    from djinn_validator.core.outcomes import OutcomeAttestor
    from djinn_validator.core.purchase import PurchaseOrchestrator
    from djinn_validator.core.shares import ShareStore

    store = ShareStore()
    store.store(
        signal_id="test-signal-1",
        genius_address="0x" + "ab" * 20,
        share=Share(x=3, y=12345),
        encrypted_key_share=b"\x00" * 32,
    )

    app = create_app(
        share_store=store,
        purchase_orch=PurchaseOrchestrator(share_store=store),
        outcome_attestor=OutcomeAttestor(),
        mpc_coordinator=MPCCoordinator(),
    )
    return TestClient(app)


class TestShareInfoEndpoint:
    """Test GET /v1/signal/{id}/share_info."""

    def test_share_info_found(self, test_app: TestClient) -> None:
        resp = test_app.get("/v1/signal/test-signal-1/share_info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["signal_id"] == "test-signal-1"
        assert data["share_x"] == 3
        assert "share_y" not in data

    def test_share_info_not_found(self, test_app: TestClient) -> None:
        resp = test_app.get("/v1/signal/nonexistent/share_info")
        assert resp.status_code == 404

    def test_share_info_invalid_id(self, test_app: TestClient) -> None:
        resp = test_app.get("/v1/signal/invalid id!/share_info")
        assert resp.status_code == 400


class TestOTSetupEndpoint:
    """Test POST /v1/mpc/ot/setup."""

    def test_setup_accepted(self, test_app: TestClient) -> None:
        resp = test_app.post(
            "/v1/mpc/ot/setup",
            json={
                "session_id": "ot-test-1",
                "n_triples": 2,
                "x_coords": [1, 2, 3],
                "threshold": 2,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True
        assert len(data["sender_public_keys"]) == 2

    def test_setup_idempotent(self, test_app: TestClient) -> None:
        payload = {
            "session_id": "ot-test-idem",
            "n_triples": 1,
            "x_coords": [1, 2],
            "threshold": 2,
        }
        resp1 = test_app.post("/v1/mpc/ot/setup", json=payload)
        resp2 = test_app.post("/v1/mpc/ot/setup", json=payload)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["sender_public_keys"] == resp2.json()["sender_public_keys"]


class TestOTEndpointErrors:
    """Test error cases for OT endpoints."""

    def test_choices_unknown_session(self, test_app: TestClient) -> None:
        resp = test_app.post(
            "/v1/mpc/ot/choices",
            json={
                "session_id": "nonexistent",
                "peer_sender_pks": {},
                "choices": {},
            },
        )
        assert resp.status_code == 404

    def test_transfers_unknown_session(self, test_app: TestClient) -> None:
        resp = test_app.post(
            "/v1/mpc/ot/transfers",
            json={
                "session_id": "nonexistent",
                "peer_choices": {},
            },
        )
        assert resp.status_code == 404

    def test_complete_unknown_session(self, test_app: TestClient) -> None:
        resp = test_app.post(
            "/v1/mpc/ot/complete",
            json={
                "session_id": "nonexistent",
                "peer_transfers": {},
                "own_sender_shares": {},
            },
        )
        assert resp.status_code == 404

    def test_shares_unknown_session(self, test_app: TestClient) -> None:
        resp = test_app.post(
            "/v1/mpc/ot/shares",
            json={
                "session_id": "nonexistent",
                "party_x": 1,
            },
        )
        assert resp.status_code == 404

    def test_shares_before_completion(self, test_app: TestClient) -> None:
        test_app.post(
            "/v1/mpc/ot/setup",
            json={
                "session_id": "ot-incomplete",
                "n_triples": 1,
                "x_coords": [1, 2],
                "threshold": 2,
            },
        )
        resp = test_app.post(
            "/v1/mpc/ot/shares",
            json={
                "session_id": "ot-incomplete",
                "party_x": 1,
            },
        )
        assert resp.status_code == 425
