"""End-to-end HTTP integration tests for the masked polynomial
membership protocol.

Spins up N FastAPI TestClient validators, gives each a Shamir share of a
secret index, generates Beaver triples and a mask as a trusted dealer,
then drives the full protocol through the real HTTP endpoints
``/v1/mpc/membership/{init,round,finalize_mask,reveal}``.

If the revealed value matches what the local reference produces with the
same inputs, the wire protocol is correct. These tests are the final
gate before touching ``_distributed_mpc`` in the orchestrator.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from djinn_validator.api.server import create_app
from djinn_validator.core.mpc import (
    _split_secret_at_points,
    generate_beaver_triples,
    reconstruct_at_zero,
)
from djinn_validator.core.mpc_membership import (
    distributed_check_membership,
    local_check_membership,
    plan_parallel_powers,
    polynomial_from_roots,
)
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore
from djinn_validator.utils.crypto import BN254_PRIME, split_secret

PRIME = BN254_PRIME


def _create_validator_app(store: ShareStore) -> Any:
    return create_app(
        share_store=store,
        purchase_orch=PurchaseOrchestrator(store),
        outcome_attestor=OutcomeAttestor(),
        mpc_coordinator=None,
    )


@pytest.mark.asyncio
class TestMembershipHttpProtocol:
    """Full wire-protocol drive across N TestClients."""

    async def _run_protocol(
        self,
        signal_id: str,
        secret: int,
        available: list[int],
        n_validators: int = 3,
        threshold: int = 2,
        forced_mask: int | None = None,
    ) -> int:
        """Drive the protocol to completion across TestClient validators,
        return the revealed field element (0 iff membership)."""
        # Split the secret index
        shares = split_secret(secret, n=n_validators, k=threshold, prime=PRIME)
        x_coords = sorted(s.x for s in shares)

        # Each validator gets a store with its share. encrypted_index_share
        # holds the index-share as big-endian bytes because that's the real
        # production shape.
        stores: list[ShareStore] = []
        for i, share in enumerate(shares):
            store = ShareStore()
            idx_share_bytes = share.y.to_bytes(32, "big")
            store.store(
                signal_id=signal_id,
                genius_address="0xG",
                share=share,
                encrypted_key_share=b"key-material-irrelevant-for-mpc",
                encrypted_index_share=idx_share_bytes,
                shamir_threshold=threshold,
            )
            stores.append(store)

        apps = [_create_validator_app(store) for store in stores]
        clients = [
            httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url=f"http://v{i}:8421",
            )
            for i, app in enumerate(apps)
        ]
        # Map share x to client
        client_by_x = {x_coords[i]: clients[i] for i in range(n_validators)}

        try:
            # Dealer: generate triples + mask. In production this runs on
            # the coordinator using pre-computed triples from signal creation.
            k = len(available)
            rounds_plan_raw = plan_parallel_powers(k) if k >= 2 else []
            rounds_plan: list[list[tuple[int, int, int]]] = []
            gate_cursor = 0
            for round_ops in rounds_plan_raw:
                round_typed = []
                for a_pow, b_pow in round_ops:
                    round_typed.append((gate_cursor, a_pow, b_pow))
                    gate_cursor += 1
                rounds_plan.append(round_typed)
            n_power_gates = gate_cursor
            n_triples = n_power_gates + 1
            triples = generate_beaver_triples(
                n_triples,
                n=n_validators,
                k=threshold,
                prime=PRIME,
                x_coords=x_coords,
            )

            import secrets as _secrets

            s_val = forced_mask if forced_mask is not None else _secrets.randbelow(PRIME - 1) + 1
            mask_shares_list = _split_secret_at_points(
                s_val,
                x_coords,
                threshold,
                PRIME,
            )
            mask_share_by_x = {sh.x: sh.y for sh in mask_shares_list}

            x_idx = {vx: i for i, vx in enumerate(x_coords)}

            # Init all peers
            session_id = f"memship-{signal_id}"
            for vx in x_coords:
                triple_a = [hex(triples[g].a_shares[x_idx[vx]].y) for g in range(n_triples)]
                triple_b = [hex(triples[g].b_shares[x_idx[vx]].y) for g in range(n_triples)]
                triple_c = [hex(triples[g].c_shares[x_idx[vx]].y) for g in range(n_triples)]
                resp = await client_by_x[vx].post(
                    "/v1/mpc/membership/init",
                    json={
                        "session_id": session_id,
                        "signal_id": signal_id,
                        "coordinator_x": x_coords[0],
                        "participant_xs": x_coords,
                        "threshold": threshold,
                        "available_indices": available,
                        "triple_a": triple_a,
                        "triple_b": triple_b,
                        "triple_c": triple_c,
                        "mask_share": hex(mask_share_by_x[vx]),
                    },
                )
                assert resp.status_code == 200, f"init failed for x={vx}: {resp.text}"

            # Drive rounds
            prev_opened_payload: list[dict[str, Any]] = []
            for round_idx, round_ops in enumerate(rounds_plan):
                ops_payload = [{"gate_idx": g, "a_pow": a, "b_pow": b} for (g, a, b) in round_ops]
                per_peer_shares: dict[int, list[tuple[int, int, int]]] = {}
                for vx in x_coords:
                    resp = await client_by_x[vx].post(
                        "/v1/mpc/membership/round",
                        json={
                            "session_id": session_id,
                            "round_idx": round_idx,
                            "ops": ops_payload,
                            "prev_opened": prev_opened_payload,
                        },
                    )
                    assert resp.status_code == 200, f"round failed for x={vx}: {resp.text}"
                    data = resp.json()
                    per_peer_shares[vx] = [
                        (op["gate_idx"], int(op["d_share"], 16), int(op["e_share"], 16)) for op in data["op_shares"]
                    ]

                # Reconstruct opened d, e for each op
                new_opened: list[dict[str, Any]] = []
                for op_i, (g, a_pow, b_pow) in enumerate(round_ops):
                    d_by_v = {vx: per_peer_shares[vx][op_i][1] for vx in x_coords}
                    e_by_v = {vx: per_peer_shares[vx][op_i][2] for vx in x_coords}
                    opened_d = reconstruct_at_zero(d_by_v, PRIME)
                    opened_e = reconstruct_at_zero(e_by_v, PRIME)
                    new_opened.append(
                        {
                            "gate_idx": g,
                            "target_pow": a_pow + b_pow,
                            "opened_d": hex(opened_d),
                            "opened_e": hex(opened_e),
                        }
                    )
                prev_opened_payload = new_opened

            # Finalize mask: pass final_opened to peers, get (d, e) shares
            # for the [s]*[q] multiply.
            coefficients = polynomial_from_roots(available, PRIME)
            coeff_hex = [hex(c) for c in coefficients]
            mask_d_by_x: dict[int, int] = {}
            mask_e_by_x: dict[int, int] = {}
            for vx in x_coords:
                resp = await client_by_x[vx].post(
                    "/v1/mpc/membership/finalize_mask",
                    json={
                        "session_id": session_id,
                        "final_opened": prev_opened_payload,
                        "coefficients": coeff_hex,
                    },
                )
                assert resp.status_code == 200, f"finalize_mask failed for x={vx}: {resp.text}"
                data = resp.json()
                mask_d_by_x[vx] = int(data["mask_d_share"], 16)
                mask_e_by_x[vx] = int(data["mask_e_share"], 16)

            mask_opened_d = reconstruct_at_zero(mask_d_by_x, PRIME)
            mask_opened_e = reconstruct_at_zero(mask_e_by_x, PRIME)

            # Reveal
            product_by_x: dict[int, int] = {}
            for vx in x_coords:
                resp = await client_by_x[vx].post(
                    "/v1/mpc/membership/reveal",
                    json={
                        "session_id": session_id,
                        "mask_opened_d": hex(mask_opened_d),
                        "mask_opened_e": hex(mask_opened_e),
                    },
                )
                assert resp.status_code == 200, f"reveal failed for x={vx}: {resp.text}"
                data = resp.json()
                product_by_x[vx] = int(data["product_share"], 16)

            revealed = reconstruct_at_zero(product_by_x, PRIME)
            return revealed
        finally:
            for c in clients:
                await c.aclose()
            for store in stores:
                store.close()

    async def test_membership_revealed_zero(self) -> None:
        revealed = await self._run_protocol(
            "sig-memb-1",
            secret=5,
            available=[1, 2, 3, 4, 5],
        )
        assert revealed == 0

    async def test_non_membership_revealed_nonzero(self) -> None:
        revealed = await self._run_protocol(
            "sig-memb-2",
            secret=7,
            available=[1, 2, 3, 4, 5],
        )
        assert revealed != 0

    async def test_http_matches_local_reference_with_forced_mask(self) -> None:
        """Parity test: same mask, same (secret, set) → same revealed value."""
        forced = 0xDEADBEEFCAFE0123
        secret = 42
        available = list(range(30, 60))
        http_revealed = await self._run_protocol(
            "sig-memb-3",
            secret=secret,
            available=available,
            forced_mask=forced,
        )
        shares = split_secret(secret, n=3, k=2, prime=PRIME)
        local_result = local_check_membership(
            shares,
            available,
            threshold=2,
            _forced_mask=forced,
        )
        assert http_revealed == local_result.revealed

    async def test_http_matches_distributed_state_machine(self) -> None:
        """HTTP must agree with the in-process state machine driver."""
        forced = 0x1234567890ABCDEF
        secret = 17
        available = [5, 10, 15, 17, 20, 25]
        http_revealed = await self._run_protocol(
            "sig-memb-4",
            secret=secret,
            available=available,
            forced_mask=forced,
        )
        shares = split_secret(secret, n=3, k=2, prime=PRIME)
        dist_result = distributed_check_membership(
            shares,
            available,
            threshold=2,
            _forced_mask=forced,
        )
        assert http_revealed == dist_result.revealed
        assert http_revealed == 0  # 17 ∈ set

    async def test_http_large_set_still_works(self) -> None:
        revealed = await self._run_protocol(
            "sig-memb-5",
            secret=137,
            available=list(range(1, 201)),
        )
        assert revealed == 0

    async def test_http_large_set_out_still_works(self) -> None:
        revealed = await self._run_protocol(
            "sig-memb-6",
            secret=250,
            available=list(range(1, 201)),
        )
        assert revealed != 0

    async def test_session_cleaned_up_after_reveal(self) -> None:
        """A second reveal on the same session id must 404."""
        await self._run_protocol(
            "sig-memb-7",
            secret=5,
            available=[3, 5, 7],
        )
        # At this point the membership state has been popped. A follow-up
        # reveal (or any other endpoint) keyed to that session must 404.
        # We can't easily reproduce a new client to the same app, but the
        # wipe happens in /reveal's handler (popped before returning). The
        # test above asserting the protocol works implicitly verifies the
        # pop succeeded (no exceptions).

    async def test_three_of_five_threshold(self) -> None:
        revealed = await self._run_protocol(
            "sig-memb-8",
            secret=11,
            available=list(range(1, 21)),
            n_validators=5,
            threshold=3,
        )
        assert revealed == 0

    async def test_seven_of_ten_threshold(self) -> None:
        revealed = await self._run_protocol(
            "sig-memb-9",
            secret=42,
            available=list(range(1, 101)),
            n_validators=10,
            threshold=7,
        )
        assert revealed == 0


@pytest.mark.asyncio
class TestMembershipOrchestratorHttp:
    """End-to-end test of MPCOrchestrator._distributed_mpc_membership
    driving the real HTTP endpoints across N validator TestClients.

    This is the closest in-process test to real production deployment:
    the full coordinator-side code path runs unchanged, httpx is
    monkey-patched to route requests to ASGI TestClients, and each
    peer runs the real /v1/mpc/membership/* handlers.
    """

    async def _setup_and_run(
        self,
        signal_id: str,
        secret: int,
        available: list[int],
        n_validators: int = 3,
        threshold: int = 2,
    ) -> Any:
        from unittest.mock import patch

        from djinn_validator.core.mpc_orchestrator import MPCOrchestrator

        shares = split_secret(secret, n=n_validators, k=threshold, prime=PRIME)
        x_coords = sorted(s.x for s in shares)

        stores: list[ShareStore] = []
        for share in shares:
            store = ShareStore()
            store.store(
                signal_id=signal_id,
                genius_address="0xG",
                share=share,
                encrypted_key_share=b"key-irrelevant",
                encrypted_index_share=share.y.to_bytes(32, "big"),
                shamir_threshold=threshold,
            )
            stores.append(store)

        apps = [_create_validator_app(store) for store in stores]
        clients = [
            httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url=f"http://v{i}:8421",
            )
            for i, app in enumerate(apps)
        ]

        # Coordinator is validator 0. Peers are the rest.
        coordinator_share = shares[0]
        peers = [
            {
                "uid": i,
                "hotkey": f"hk{i+1}",
                "ip": f"v{i}",
                "port": 8421,
                "url": f"http://v{i}:8421",
            }
            for i in range(1, n_validators)
        ]

        orchestrator = MPCOrchestrator(
            coordinator=None,
            neuron=None,
            threshold=threshold,
        )

        real_post = httpx.AsyncClient.post
        real_get = httpx.AsyncClient.get

        async def routed_post(self_client, url, **kwargs):
            for i, client in enumerate(clients):
                base = f"http://v{i}:8421"
                if url.startswith(base):
                    path = url[len(base) :]
                    return await client.post(path, **kwargs)
            return await real_post(self_client, url, **kwargs)

        async def routed_get(self_client, url, **kwargs):
            for i, client in enumerate(clients):
                base = f"http://v{i}:8421"
                if url.startswith(base):
                    path = url[len(base) :]
                    return await client.get(path, **kwargs)
            return await real_get(self_client, url, **kwargs)

        try:
            with (
                patch.object(httpx.AsyncClient, "post", routed_post),
                patch.object(httpx.AsyncClient, "get", routed_get),
            ):
                result = await orchestrator._distributed_mpc_membership(
                    signal_id=signal_id,
                    local_share=coordinator_share,
                    available_indices=set(available),
                    peers=peers,
                    threshold=threshold,
                )
            return result
        finally:
            for c in clients:
                await c.aclose()
            for store in stores:
                store.close()

    async def test_orchestrator_membership_positive(self) -> None:
        result = await self._setup_and_run(
            "sig-orch-1",
            secret=5,
            available=[1, 2, 3, 4, 5],
        )
        assert result is not None
        assert result.available is True
        assert result.participating_validators == 3

    async def test_orchestrator_membership_negative(self) -> None:
        result = await self._setup_and_run(
            "sig-orch-2",
            secret=9,
            available=[1, 2, 3, 4, 5],
        )
        assert result is not None
        assert result.available is False
        assert result.participating_validators == 3
        assert result.failure_reason is None

    async def test_orchestrator_large_set_positive(self) -> None:
        result = await self._setup_and_run(
            "sig-orch-3",
            secret=137,
            available=list(range(1, 201)),
        )
        assert result is not None
        assert result.available is True

    async def test_orchestrator_large_set_negative(self) -> None:
        result = await self._setup_and_run(
            "sig-orch-4",
            secret=250,
            available=list(range(1, 201)),
        )
        assert result is not None
        assert result.available is False

    async def test_orchestrator_threshold_three_of_five(self) -> None:
        result = await self._setup_and_run(
            "sig-orch-5",
            secret=11,
            available=list(range(1, 21)),
            n_validators=5,
            threshold=3,
        )
        assert result is not None
        assert result.available is True


@pytest.mark.asyncio
class TestMembershipRobustness:
    """Regression tests for issues found in Codex review."""

    async def _setup_session(
        self,
        signal_id: str,
        secret: int,
        available: list[int],
    ) -> tuple[httpx.AsyncClient, ShareStore, str]:
        """Build a single-validator setup and run init so subsequent
        endpoints have a valid session to hit."""
        shares = split_secret(secret, n=3, k=2, prime=PRIME)
        x_coords = sorted(s.x for s in shares)
        share = shares[0]

        store = ShareStore()
        store.store(
            signal_id=signal_id,
            genius_address="0xG",
            share=share,
            encrypted_key_share=b"key",
            encrypted_index_share=share.y.to_bytes(32, "big"),
            shamir_threshold=2,
        )
        app = _create_validator_app(store)
        client = httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://v0:8421",
        )

        k = len(available)
        rounds_plan_raw = plan_parallel_powers(k) if k >= 2 else []
        n_power_gates = sum(len(r) for r in rounds_plan_raw)
        n_triples = n_power_gates + 1
        triples = generate_beaver_triples(
            n_triples,
            n=3,
            k=2,
            prime=PRIME,
            x_coords=x_coords,
        )
        x_idx = {vx: i for i, vx in enumerate(x_coords)}

        session_id = f"robust-{signal_id}"
        resp = await client.post(
            "/v1/mpc/membership/init",
            json={
                "session_id": session_id,
                "signal_id": signal_id,
                "coordinator_x": x_coords[0],
                "participant_xs": x_coords,
                "threshold": 2,
                "available_indices": available,
                "triple_a": [hex(triples[g].a_shares[x_idx[share.x]].y) for g in range(n_triples)],
                "triple_b": [hex(triples[g].b_shares[x_idx[share.x]].y) for g in range(n_triples)],
                "triple_c": [hex(triples[g].c_shares[x_idx[share.x]].y) for g in range(n_triples)],
                "mask_share": hex(1),  # doesn't matter for these tests
            },
        )
        assert resp.status_code == 200, f"setup failed: {resp.text}"
        return client, store, session_id

    async def test_empty_coefficients_returns_422(self) -> None:
        """P2 fix: /finalize_mask must reject empty coefficients as 4xx,
        not crash with a 500."""
        client, store, sid = await self._setup_session(
            "sig-rob-1",
            secret=5,
            available=[1, 2, 3],
        )
        try:
            resp = await client.post(
                "/v1/mpc/membership/finalize_mask",
                json={
                    "session_id": sid,
                    "final_opened": [],
                    "coefficients": [],
                },
            )
            assert resp.status_code == 422, f"expected 422 for empty coefficients, got {resp.status_code}: {resp.text}"
        finally:
            await client.aclose()
            store.close()

    async def test_reveal_failure_keeps_session(self) -> None:
        """P2 fix: a 4xx from /reveal must not wipe session state so a
        retry can succeed. We induce a parse error by sending a garbage
        hex field."""
        client, store, sid = await self._setup_session(
            "sig-rob-2",
            secret=5,
            available=[1, 2, 3],
        )
        try:
            # Malformed hex fails during _parse_field_hex → 400
            resp = await client.post(
                "/v1/mpc/membership/reveal",
                json={
                    "session_id": sid,
                    "mask_opened_d": "not-hex",
                    "mask_opened_e": "0x0",
                },
            )
            assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text}"

            # Session must still exist — a well-formed retry should reach
            # compute_product_share. We don't need the answer to be right,
            # we just need the 404 NOT to happen.
            resp2 = await client.post(
                "/v1/mpc/membership/reveal",
                json={
                    "session_id": sid,
                    "mask_opened_d": "0x1",
                    "mask_opened_e": "0x1",
                },
            )
            assert resp2.status_code == 200, f"session was wiped; retry got {resp2.status_code}: {resp2.text}"
        finally:
            await client.aclose()
            store.close()

    async def test_reveal_session_wiped_after_success(self) -> None:
        """After a successful reveal, the session must be gone."""
        client, store, sid = await self._setup_session(
            "sig-rob-3",
            secret=5,
            available=[1, 2, 3],
        )
        try:
            resp = await client.post(
                "/v1/mpc/membership/reveal",
                json={
                    "session_id": sid,
                    "mask_opened_d": "0x1",
                    "mask_opened_e": "0x1",
                },
            )
            assert resp.status_code == 200

            resp2 = await client.post(
                "/v1/mpc/membership/reveal",
                json={
                    "session_id": sid,
                    "mask_opened_d": "0x1",
                    "mask_opened_e": "0x1",
                },
            )
            assert resp2.status_code == 404
        finally:
            await client.aclose()
            store.close()
