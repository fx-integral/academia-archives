"""Tests for the MPC orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

import pytest

from djinn_validator.core.mpc_coordinator import MPCCoordinator
from djinn_validator.core.mpc_orchestrator import MPCOrchestrator, _is_public_ip
from djinn_validator.utils.crypto import Share, generate_signal_index_shares, split_secret


class TestSingleValidatorMode:
    """When no neuron/metagraph is available, falls back to prototype."""

    @pytest.mark.asyncio
    async def test_single_validator_available(self) -> None:
        """Signal index IS in available set."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=1)

        # k=1 means constant polynomial, single share suffices
        shares = split_secret(5, n=1, k=1)
        result = await orch.check_availability(
            signal_id="sig-1",
            local_share=shares[0],
            available_indices={1, 3, 5, 7, 9},
        )
        assert result.available is True

    @pytest.mark.asyncio
    async def test_single_validator_unavailable(self) -> None:
        """Signal index NOT in available set."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=1)

        shares = split_secret(5, n=1, k=1)
        result = await orch.check_availability(
            signal_id="sig-1",
            local_share=shares[0],
            available_indices={1, 3, 7, 9},  # 5 not included
        )
        assert result.available is False


class TestPeerDiscovery:
    """Test validator peer discovery from metagraph."""

    def test_no_neuron_returns_empty(self) -> None:
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        assert orch._get_peer_validators() == []

    def test_discovers_validators(self) -> None:
        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 0
        neuron.metagraph.n.item.return_value = 3
        neuron.metagraph.validator_permit = [
            MagicMock(item=MagicMock(return_value=True)),  # uid 0 (us)
            MagicMock(item=MagicMock(return_value=True)),  # uid 1 (peer)
            MagicMock(item=MagicMock(return_value=False)),  # uid 2 (miner)
        ]
        neuron.metagraph.hotkeys = ["key0", "key1", "key2"]

        axon0 = MagicMock(ip="1.1.1.1", port=8421)
        axon1 = MagicMock(ip="2.2.2.2", port=8421)
        axon2 = MagicMock(ip="3.3.3.3", port=8422)
        neuron.metagraph.axons = [axon0, axon1, axon2]

        orch = MPCOrchestrator(coordinator=coord, neuron=neuron)
        peers = orch._get_peer_validators()

        assert len(peers) == 1
        assert peers[0]["uid"] == 1
        assert peers[0]["hotkey"] == "key1"
        assert peers[0]["url"] == "http://2.2.2.2:8421"

    def test_skips_zero_ip(self) -> None:
        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 0
        neuron.metagraph.n.item.return_value = 2
        neuron.metagraph.validator_permit = [
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
        ]
        neuron.metagraph.hotkeys = ["key0", "key1"]
        neuron.metagraph.axons = [
            MagicMock(ip="1.1.1.1", port=8421),
            MagicMock(ip="0.0.0.0", port=8421),  # Not announced
        ]

        orch = MPCOrchestrator(coordinator=coord, neuron=neuron)
        assert len(orch._get_peer_validators()) == 0

    def test_skips_empty_ip(self) -> None:
        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 0
        neuron.metagraph.n.item.return_value = 2
        neuron.metagraph.validator_permit = [
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
        ]
        neuron.metagraph.hotkeys = ["key0", "key1"]
        neuron.metagraph.axons = [
            MagicMock(ip="1.1.1.1", port=8421),
            MagicMock(ip="", port=8421),
        ]
        orch = MPCOrchestrator(coordinator=coord, neuron=neuron)
        assert len(orch._get_peer_validators()) == 0


class TestSelfLoopbackUrl:
    """v1685 invariant: shadow_settle addresses self via 127.0.0.1, not
    its own external IP. NAT hairpin on operator validator hosts (UID 1, 86
    historically) silently broke coordinator self-init when the address
    came from metagraph axon.ip. Don't regress this."""

    def test_uses_loopback_not_external_ip(self) -> None:
        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 1
        neuron.metagraph.axons = [
            MagicMock(ip="8.8.8.8", port=8421),
            MagicMock(ip="167.150.153.103", port=8421),  # UID 1's real ext IP
            MagicMock(ip="34.58.165.14", port=8421),
        ]
        orch = MPCOrchestrator(coordinator=coord, neuron=neuron)
        url = orch._self_loopback_url()
        assert url == "http://127.0.0.1:8421"
        assert "167.150.153.103" not in (url or "")

    def test_returns_none_without_metagraph(self) -> None:
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        assert orch._self_loopback_url() is None

    def test_returns_none_when_port_missing(self) -> None:
        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 0
        neuron.metagraph.axons = [MagicMock(ip="1.2.3.4", port=0)]
        orch = MPCOrchestrator(coordinator=coord, neuron=neuron)
        assert orch._self_loopback_url() is None

    def test_uses_published_port_not_default(self) -> None:
        """Custom-port validators (e.g. 9001) must inherit that port."""
        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 0
        neuron.metagraph.axons = [MagicMock(ip="1.2.3.4", port=9001)]
        orch = MPCOrchestrator(coordinator=coord, neuron=neuron)
        assert orch._self_loopback_url() == "http://127.0.0.1:9001"


class TestSSRFProtection:
    """Test SSRF protection in peer IP validation."""

    def test_public_ip_allowed(self) -> None:
        assert _is_public_ip("8.8.8.8") is True
        assert _is_public_ip("1.2.3.4") is True

    def test_private_ip_rejected(self) -> None:
        assert _is_public_ip("10.0.0.1") is False
        assert _is_public_ip("172.16.0.1") is False
        assert _is_public_ip("192.168.1.1") is False

    def test_loopback_rejected(self) -> None:
        assert _is_public_ip("127.0.0.1") is False

    def test_link_local_rejected(self) -> None:
        assert _is_public_ip("169.254.1.1") is False

    def test_invalid_ip_rejected(self) -> None:
        assert _is_public_ip("not-an-ip") is False
        assert _is_public_ip("") is False

    def test_private_ip_peer_skipped(self) -> None:
        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 0
        neuron.metagraph.n.item.return_value = 3
        neuron.metagraph.validator_permit = [
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
        ]
        neuron.metagraph.hotkeys = ["key0", "key1", "key2"]
        neuron.metagraph.axons = [
            MagicMock(ip="8.8.8.8", port=8421),  # us
            MagicMock(ip="192.168.1.1", port=8421),  # private — should be skipped
            MagicMock(ip="1.2.3.4", port=8421),  # public peer
        ]

        orch = MPCOrchestrator(coordinator=coord, neuron=neuron)
        peers = orch._get_peer_validators()

        assert len(peers) == 1
        assert peers[0]["uid"] == 2
        assert peers[0]["ip"] == "1.2.3.4"


class TestCollectPeerShares:
    """Test _collect_peer_share_xs with various failure modes."""

    @pytest.mark.asyncio
    async def test_collects_shares_from_peers(self, httpx_mock) -> None:
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        peers = [
            {"uid": 1, "url": "http://peer1:8421"},
            {"uid": 2, "url": "http://peer2:8421"},
        ]
        httpx_mock.add_response(
            url="http://peer1:8421/v1/signal/sig-1/share_info",
            json={"share_x": 1},
        )
        httpx_mock.add_response(
            url="http://peer2:8421/v1/signal/sig-1/share_info",
            json={"share_x": 2},
        )
        xs = await orch._collect_peer_share_xs(peers, "sig-1")
        assert len(xs) == 2
        assert xs[0] == 1
        assert xs[1] == 2

    @pytest.mark.asyncio
    async def test_partial_peer_failure(self, httpx_mock) -> None:
        """One peer returns 500 (retried), the other succeeds."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        peers = [
            {"uid": 1, "url": "http://peer1:8421"},
            {"uid": 2, "url": "http://peer2:8421"},
        ]
        # Register enough 500 responses for retries (initial + 2 retries = 3)
        for _ in range(orch._PEER_RETRIES + 1):
            httpx_mock.add_response(
                url="http://peer1:8421/v1/signal/sig-1/share_info",
                status_code=500,
            )
        httpx_mock.add_response(
            url="http://peer2:8421/v1/signal/sig-1/share_info",
            json={"share_x": 2},
        )
        xs = await orch._collect_peer_share_xs(peers, "sig-1")
        assert len(xs) == 1
        assert xs[0] == 2

    @pytest.mark.asyncio
    async def test_malformed_json_response(self, httpx_mock) -> None:
        """Peer returns JSON missing required fields."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        peers = [{"uid": 1, "url": "http://peer1:8421"}]
        httpx_mock.add_response(
            url="http://peer1:8421/v1/signal/sig-1/share_info",
            json={"signal_id": "sig-1"},  # Missing share_x
        )
        xs = await orch._collect_peer_share_xs(peers, "sig-1")
        assert len(xs) == 0

    @pytest.mark.asyncio
    async def test_all_peers_fail(self, httpx_mock) -> None:
        """All peers fail (with retries) — returns empty list."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        peers = [
            {"uid": 1, "url": "http://peer1:8421"},
            {"uid": 2, "url": "http://peer2:8421"},
        ]
        for _ in range(orch._PEER_RETRIES + 1):
            httpx_mock.add_response(
                url="http://peer1:8421/v1/signal/sig-1/share_info",
                status_code=503,
            )
            httpx_mock.add_response(
                url="http://peer2:8421/v1/signal/sig-1/share_info",
                status_code=503,
            )
        shares = await orch._collect_peer_share_xs(peers, "sig-1")
        assert len(shares) == 0

    @pytest.mark.asyncio
    async def test_empty_peers_returns_empty(self) -> None:
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        shares = await orch._collect_peer_share_xs([], "sig-1")
        assert shares == []

    @pytest.mark.asyncio
    async def test_json_decode_error_handled(self, httpx_mock) -> None:
        """Peer returns non-JSON response — should be caught gracefully."""
        import httpx as httpx_lib

        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        peers = [{"uid": 1, "url": "http://peer1:8421"}]
        httpx_mock.add_response(
            url="http://peer1:8421/v1/signal/sig-1/share_info",
            text="not valid json",
            headers={"content-type": "text/plain"},
        )
        shares = await orch._collect_peer_share_xs(peers, "sig-1")
        assert len(shares) == 0


class TestDistributedMPC:
    """Test _distributed_mpc with various scenarios."""

    def _make_peers(self, count: int) -> list[dict]:
        return [{"uid": i + 1, "url": f"http://peer{i + 1}:8421"} for i in range(count)]

    @pytest.mark.asyncio
    async def test_insufficient_participants_returns_none(self) -> None:
        """When deduplicated participant_xs < threshold, return None."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=7)

        # Only 3 peers (+ self = 4 participants, below threshold 7)
        peers = self._make_peers(3)
        share = Share(x=1, y=42)

        result = await orch._distributed_mpc("sig-1", share, {1, 3, 5}, peers)
        assert result is not None and not result.available

    @pytest.mark.asyncio
    async def test_all_peers_reject_init_returns_none(self, httpx_mock) -> None:
        """When all peers reject MPC init, returns None."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=3)

        peers = self._make_peers(5)
        share = Share(x=1, y=42)

        # Mock share_info for peer discovery
        for i in range(5):
            httpx_mock.add_response(
                url=f"http://peer{i + 1}:8421/v1/signal/sig-1/share_info",
                json={"signal_id": "sig-1", "share_x": i + 2},
            )

        # All peers reject
        for i in range(5):
            httpx_mock.add_response(
                url=f"http://peer{i + 1}:8421/v1/mpc/init",
                json={"accepted": False},
            )

        result = await orch._distributed_mpc("sig-1", share, {1, 3}, peers)
        assert result is not None and not result.available

    @pytest.mark.asyncio
    async def test_peer_init_http_error_handled(self, httpx_mock) -> None:
        """HTTP errors during init are caught gracefully (with retries)."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=3)

        peers = self._make_peers(5)
        share = Share(x=1, y=42)

        # Mock share_info for peer discovery
        for i in range(5):
            httpx_mock.add_response(
                url=f"http://peer{i + 1}:8421/v1/signal/sig-1/share_info",
                json={"signal_id": "sig-1", "share_x": i + 2},
            )

        # All peers return 500, register enough for retries
        for _ in range(orch._PEER_RETRIES + 1):
            for i in range(5):
                httpx_mock.add_response(
                    url=f"http://peer{i + 1}:8421/v1/mpc/init",
                    status_code=500,
                )

        result = await orch._distributed_mpc("sig-1", share, {1}, peers)
        assert result is not None and not result.available

    @pytest.mark.asyncio
    async def test_peer_init_json_decode_error(self, httpx_mock) -> None:
        """Non-JSON response during MPC init should be caught gracefully."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=3)

        peers = self._make_peers(5)
        share = Share(x=1, y=42)

        # Mock share_info for peer discovery
        for i in range(5):
            httpx_mock.add_response(
                url=f"http://peer{i + 1}:8421/v1/signal/sig-1/share_info",
                json={"signal_id": "sig-1", "share_x": i + 2},
            )

        for i in range(5):
            httpx_mock.add_response(
                url=f"http://peer{i + 1}:8421/v1/mpc/init",
                text="not json",
                headers={"content-type": "text/plain"},
            )

        result = await orch._distributed_mpc("sig-1", share, {1}, peers)
        assert result is not None and not result.available

    @pytest.mark.asyncio
    async def test_duplicate_x_coords_deduplicated(self) -> None:
        """When local share.x equals a peer uid+1, duplicates are removed."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=7)

        # local_share.x = 2, peer uid=1 → uid+1=2, same x-coordinate
        peers = [{"uid": 1, "url": "http://peer1:8421"}]
        share = Share(x=2, y=42)

        # Only 1 unique participant (x=2), well below threshold 7
        result = await orch._distributed_mpc("sig-1", share, {1}, peers)
        assert result is not None and not result.available


class TestFallbackBehavior:
    """Test that orchestrator correctly falls back when peers unavailable."""

    @pytest.mark.asyncio
    async def test_no_peers_uses_prototype(self) -> None:
        """With no peers, uses single-validator prototype."""
        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 0
        neuron.metagraph.n.item.return_value = 1
        neuron.metagraph.validator_permit = [
            MagicMock(item=MagicMock(return_value=True)),
        ]
        neuron.metagraph.hotkeys = ["key0"]
        neuron.metagraph.axons = [MagicMock(ip="1.1.1.1", port=8421)]

        orch = MPCOrchestrator(coordinator=coord, neuron=neuron, threshold=1)
        shares = split_secret(3, n=1, k=1)

        result = await orch.check_availability(
            signal_id="sig-1",
            local_share=shares[0],
            available_indices={1, 3, 5},
        )
        assert result.available is True
        assert result.participating_validators == 1


class TestPeerRetryBehavior:
    """Test that _peer_request retries correctly."""

    @pytest.mark.asyncio
    async def test_succeeds_after_transient_500(self, httpx_mock) -> None:
        """Request succeeds on third attempt after two 500s."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)

        # Two failures, then success
        httpx_mock.add_response(url="http://peer:8421/test", status_code=500)
        httpx_mock.add_response(url="http://peer:8421/test", status_code=500)
        httpx_mock.add_response(url="http://peer:8421/test", json={"ok": True})

        resp = await orch._peer_request("get", "http://peer:8421/test")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_no_retry_on_4xx(self, httpx_mock) -> None:
        """4xx responses are returned immediately without retry."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)

        httpx_mock.add_response(url="http://peer:8421/test", status_code=404)

        resp = await orch._peer_request("get", "http://peer:8421/test")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self, httpx_mock) -> None:
        """Raises after all retry attempts fail."""
        import httpx as httpx_lib

        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)

        for _ in range(orch._PEER_RETRIES + 1):
            httpx_mock.add_response(url="http://peer:8421/test", status_code=502)

        with pytest.raises(httpx_lib.HTTPStatusError):
            await orch._peer_request("get", "http://peer:8421/test")

    @pytest.mark.asyncio
    async def test_close_releases_client(self) -> None:
        """close() shuts down the shared HTTP client."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        await orch.close()
        assert orch._http.is_closed


class TestGatherTimeouts:
    """Test that gather operations have proper timeouts."""

    def _make_peers(self, count: int) -> list[dict]:
        return [{"uid": i + 1, "url": f"http://peer{i + 1}:8421"} for i in range(count)]

    @pytest.mark.asyncio
    async def test_gather_timeout_constant_exists(self) -> None:
        """GATHER_TIMEOUT should be derived from PEER_TIMEOUT."""
        from djinn_validator.core.mpc_orchestrator import GATHER_TIMEOUT, PEER_TIMEOUT

        assert GATHER_TIMEOUT == PEER_TIMEOUT * 3

    @pytest.mark.asyncio
    async def test_peer_init_timeout_returns_none(self, monkeypatch) -> None:
        """When peer init gather times out, returns None gracefully."""
        import asyncio
        import djinn_validator.core.mpc_orchestrator as orch_module

        # Set a very short gather timeout
        monkeypatch.setattr(orch_module, "GATHER_TIMEOUT", 0.001)

        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=3)
        peers = self._make_peers(5)
        share = Share(x=1, y=42)

        # Monkey-patch _peer_request to sleep forever
        async def _slow_request(*args, **kwargs):
            await asyncio.sleep(100)

        monkeypatch.setattr(orch, "_peer_request", _slow_request)

        result = await orch._distributed_mpc("sig-1", share, {1, 3}, peers)
        assert result is not None and not result.available

    @pytest.mark.asyncio
    async def test_empty_available_indices_returns_unavailable(self) -> None:
        """When available_indices is empty, returns unavailable immediately."""
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None, threshold=3)
        peers = self._make_peers(5)
        share = Share(x=1, y=42)

        result = await orch._distributed_mpc("sig-1", share, set(), peers)
        assert result is not None
        assert result.available is False


class TestPurchaseOddsPrefetch:
    """P0-01 follow-on (v1434): on-demand pull of BPA/WPA from peers when
    the local ledger is missing rows for signals in the audit set."""

    def _make_neuron_with_one_peer(self, peer_ip: str = "1.2.3.4", peer_port: int = 8421):
        neuron = MagicMock()
        neuron.uid = 0
        neuron.wallet = MagicMock()
        neuron.metagraph.n.item.return_value = 2
        neuron.metagraph.validator_permit = [
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
        ]
        neuron.metagraph.hotkeys = ["key0", "key1"]
        neuron.metagraph.axons = [
            MagicMock(ip="10.0.0.1", port=peer_port),  # self (skipped)
            MagicMock(ip=peer_ip, port=peer_port),
        ]
        return neuron

    def _make_audit_set(
        self,
        idiot: str,
        signal_ids: list[str],
        purchase_ids: dict[str, int] | None = None,
    ):
        """Minimal stand-in for AuditSet with just what the prefetch touches.

        v1443+: prefetch reads ``purchase_id`` off each audit signal so it
        can look up the on-chain Merkle root commitment. Tests that want
        the backfill path to fire must pass ``purchase_ids`` so the
        ``int(purchase_id)`` cast is well-defined.
        """
        audit_set = MagicMock()
        audit_set.idiot_address = idiot
        signals = {}
        for sid in signal_ids:
            sig = MagicMock()
            sig.purchase_id = (purchase_ids or {}).get(sid, 0)
            signals[sid] = sig
        audit_set.signals = signals
        return audit_set

    @staticmethod
    def _make_chain_client_with_roots(
        bpas: list[int],
        wpas: list[int],
    ) -> MagicMock:
        """Build a chain_client that returns the canonical Merkle roots
        for the given vectors. Use in prefetch tests where the peer's
        response is honest."""
        from djinn_validator.utils.merkle import compute_vector_root

        bpa_root = compute_vector_root(bpas)
        wpa_root = compute_vector_root(wpas)
        client = MagicMock()
        client.get_purchase_vector_roots = AsyncMock(return_value=(bpa_root, wpa_root))
        return client

    @pytest.mark.asyncio
    async def test_prefetch_noop_when_ledger_is_none(self) -> None:
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=self._make_neuron_with_one_peer())
        audit_set = self._make_audit_set("0xaa" + "00" * 19, ["sig-1"])
        n = await orch._prefetch_missing_purchase_odds_from_peers(
            audit_set=audit_set, purchase_odds_ledger=None
        )
        assert n == 0

    @pytest.mark.asyncio
    async def test_prefetch_noop_when_neuron_is_none(self) -> None:
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger

        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        audit_set = self._make_audit_set("0xaa" + "00" * 19, ["sig-1"])
        n = await orch._prefetch_missing_purchase_odds_from_peers(
            audit_set=audit_set, purchase_odds_ledger=PurchaseOddsLedger()
        )
        assert n == 0

    @pytest.mark.asyncio
    async def test_prefetch_noop_when_all_rows_present(self) -> None:
        """If the ledger already has every (signal, buyer), no peer call happens."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=self._make_neuron_with_one_peer())
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "aa" * 20
        ledger.record(signal_id="sig-1", buyer_address=idiot, bpas=[1], wpas=[1], bpa_mode=True)
        audit_set = self._make_audit_set(idiot, ["sig-1"])

        call_count = {"n": 0}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                call_count["n"] += 1
                raise AssertionError("should not be called")

        with patch("httpx.AsyncClient", lambda **kw: FakeClient()):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0
        assert call_count["n"] == 0

    @pytest.mark.asyncio
    async def test_prefetch_writes_first_200_response(self) -> None:
        """Missing row is pulled from the first peer that returns 200."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        bpas = [1_950_000, 1_880_000]
        wpas = [1_910_000, 1_850_000]
        chain_client = self._make_chain_client_with_roots(bpas, wpas)
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "bb" * 20
        audit_set = self._make_audit_set(idiot, ["sig-1"], purchase_ids={"sig-1": 42})

        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "signal_id": "sig-1",
                    "buyer_address": idiot,
                    "bpa_mode": True,
                    "bpas": bpas,
                    "wpas": wpas,
                }

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                assert url.endswith(f"/v1/purchase_odds/sig-1/{idiot}")
                return FakeResp()

        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 1
        rec = ledger.get(signal_id="sig-1", buyer_address=idiot)
        assert rec is not None
        assert rec.bpas == bpas
        assert rec.wpas == wpas
        assert rec.bpa_mode is True
        # Root lookup was performed exactly once — before peer polling.
        chain_client.get_purchase_vector_roots.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_prefetch_falls_through_on_404(self) -> None:
        """First peer 404, second peer 200: use the second peer's data."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        neuron = MagicMock()
        neuron.uid = 0
        neuron.wallet = MagicMock()
        neuron.metagraph.n.item.return_value = 3
        neuron.metagraph.validator_permit = [
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
        ]
        neuron.metagraph.hotkeys = ["key0", "key1", "key2"]
        neuron.metagraph.axons = [
            MagicMock(ip="10.0.0.1", port=8421),
            MagicMock(ip="1.2.3.4", port=8421),
            MagicMock(ip="5.6.7.8", port=8421),
        ]
        chain_client = self._make_chain_client_with_roots([42], [41])
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=neuron,
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "cc" * 20
        audit_set = self._make_audit_set(idiot, ["sig-1"], purchase_ids={"sig-1": 77})

        class FakeResp404:
            status_code = 404

            def json(self):  # pragma: no cover - not used
                return {}

        class FakeResp200:
            status_code = 200

            def json(self):
                return {
                    "bpas": [42],
                    "wpas": [41],
                    "bpa_mode": False,
                }

        url_sequence: list[str] = []

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                url_sequence.append(url)
                if "1.2.3.4" in url:
                    return FakeResp404()
                return FakeResp200()

        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 1
        assert len(url_sequence) == 2  # first peer 404, then second peer
        rec = ledger.get(signal_id="sig-1", buyer_address=idiot)
        assert rec.bpas == [42]

    @pytest.mark.asyncio
    async def test_prefetch_tolerates_peer_timeout(self) -> None:
        """httpx.ConnectTimeout on a peer is swallowed; row stays missing."""
        import httpx
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        chain_client = self._make_chain_client_with_roots([1], [1])
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "dd" * 20
        audit_set = self._make_audit_set(idiot, ["sig-1"], purchase_ids={"sig-1": 1})

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                raise httpx.ConnectTimeout("simulated peer down")

        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0
        assert ledger.get(signal_id="sig-1", buyer_address=idiot) is None

    @pytest.mark.asyncio
    async def test_prefetch_skips_malformed_peer_response(self) -> None:
        """If peer returns 200 but response lacks bpas/wpas, don't crash."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        chain_client = self._make_chain_client_with_roots([1], [1])
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "ee" * 20
        audit_set = self._make_audit_set(idiot, ["sig-1"], purchase_ids={"sig-1": 1})

        class FakeResp:
            status_code = 200

            def json(self):
                return {"signal_id": "sig-1", "oops": "missing fields"}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                return FakeResp()

        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0
        assert ledger.get(signal_id="sig-1", buyer_address=idiot) is None


class TestPurchaseOddsPrefetchMetrics:
    """v1702: BPA/WPA prefetch ticks the bounded-cardinality counter
    PURCHASE_ODDS_PREFETCH_RESULT for each outcome. Without these,
    /metrics shows missing_bpa_wpa rolled up at build_pi but not WHY —
    operators can't distinguish 404 (gossip gap), root_mismatch
    (peer adversarial), or root_rpc_failed (chain client flaky)."""

    _helpers = TestPurchaseOddsPrefetch()

    @pytest.mark.asyncio
    async def test_prefetch_404_ticks_peer_404(self) -> None:
        from djinn_validator.api.metrics import PURCHASE_ODDS_PREFETCH_RESULT
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        chain_client = self._helpers._make_chain_client_with_roots([1], [1])
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "aa" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-1"], purchase_ids={"sig-1": 1}
        )

        class FakeResp:
            status_code = 404

            def json(self):
                return {}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                return FakeResp()

        before = PURCHASE_ODDS_PREFETCH_RESULT.labels(outcome="peer_404")._value.get()
        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        after = PURCHASE_ODDS_PREFETCH_RESULT.labels(outcome="peer_404")._value.get()
        assert after == before + 1, "404 must tick peer_404"

    @pytest.mark.asyncio
    async def test_prefetch_timeout_ticks_peer_unreachable(self) -> None:
        import httpx as _httpx
        from djinn_validator.api.metrics import PURCHASE_ODDS_PREFETCH_RESULT
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        chain_client = self._helpers._make_chain_client_with_roots([1], [1])
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "bb" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-1"], purchase_ids={"sig-1": 1}
        )

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                raise _httpx.ConnectTimeout("simulated peer down")

        before = PURCHASE_ODDS_PREFETCH_RESULT.labels(outcome="peer_unreachable")._value.get()
        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        after = PURCHASE_ODDS_PREFETCH_RESULT.labels(outcome="peer_unreachable")._value.get()
        assert after == before + 1, "httpx error must tick peer_unreachable"

    @pytest.mark.asyncio
    async def test_prefetch_success_ticks_recovered(self) -> None:
        from djinn_validator.api.metrics import PURCHASE_ODDS_PREFETCH_RESULT
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        bpas = [1_950_000]
        wpas = [1_910_000]
        chain_client = self._helpers._make_chain_client_with_roots(bpas, wpas)
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "cc" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-1"], purchase_ids={"sig-1": 42}
        )

        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "signal_id": "sig-1",
                    "buyer_address": idiot,
                    "bpa_mode": True,
                    "bpas": bpas,
                    "wpas": wpas,
                }

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                return FakeResp()

        before = PURCHASE_ODDS_PREFETCH_RESULT.labels(outcome="recovered")._value.get()
        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        after = PURCHASE_ODDS_PREFETCH_RESULT.labels(outcome="recovered")._value.get()
        assert n == 1
        assert after == before + 1, "successful fetch must tick recovered"


class TestPurchaseOddsPrefetchMerkleAuth:
    """v1443 fresh-eyes HIGH: peer-backfill must Merkle-verify vectors
    against on-chain ``purchaseBpaRoot`` / ``purchaseWpaRoot`` before
    writing to the local ledger. A single malicious validator racing
    honest peers with 200 responses could otherwise permanently corrupt
    our settlement inputs — the first 200 wins and the poisoned vectors
    flow straight into the MPC batch and the on-chain ``quality_score``.
    """

    _helpers = TestPurchaseOddsPrefetch()

    @pytest.mark.asyncio
    async def test_prefetch_fail_closed_when_no_chain_client(self) -> None:
        """Without a chain_client, we cannot verify peer data — refuse
        to record rather than trust peers blindly."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=None,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "aa" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-1"], purchase_ids={"sig-1": 1}
        )

        class _NeverCalled:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):  # pragma: no cover
                raise AssertionError("no peer call should happen without chain_client")

        with patch("httpx.AsyncClient", lambda **kw: _NeverCalled()):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0
        assert ledger.get(signal_id="sig-1", buyer_address=idiot) is None

    @pytest.mark.asyncio
    async def test_prefetch_rejects_adversarial_vectors(self) -> None:
        """Peer returns 200 but with vectors whose Merkle root does NOT
        match the on-chain commitment. Reject — do not write. This is
        the core anti-poisoning invariant."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        honest_bpas = [1_950_000, 1_880_000]
        honest_wpas = [1_910_000, 1_850_000]
        chain_client = self._helpers._make_chain_client_with_roots(
            honest_bpas, honest_wpas
        )
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "bb" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-1"], purchase_ids={"sig-1": 42}
        )

        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "bpas": [9_999_999, 9_999_999],
                    "wpas": [9_999_999, 9_999_999],
                    "bpa_mode": True,
                }

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                return FakeResp()

        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0
        assert ledger.get(signal_id="sig-1", buyer_address=idiot) is None

    @pytest.mark.asyncio
    async def test_prefetch_rejects_bpa_match_wpa_mismatch(self) -> None:
        """Half-poisoned response is still rejected. Defense against an
        adversary that learned one root but not the other."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        honest_bpas = [1_950_000]
        honest_wpas = [1_910_000]
        chain_client = self._helpers._make_chain_client_with_roots(
            honest_bpas, honest_wpas
        )
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "cc" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-1"], purchase_ids={"sig-1": 7}
        )

        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "bpas": honest_bpas,
                    "wpas": [9_999_999],
                    "bpa_mode": True,
                }

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                return FakeResp()

        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0
        assert ledger.get(signal_id="sig-1", buyer_address=idiot) is None

    @pytest.mark.asyncio
    async def test_prefetch_honest_peer_after_adversarial_peer(self) -> None:
        """Adversary racing ahead does NOT win: the honest peer's
        matching response is still accepted. Validates that the loop
        keeps polling past a mismatched peer rather than stopping at
        the first 200."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        honest_bpas = [1_950_000]
        honest_wpas = [1_910_000]
        chain_client = self._helpers._make_chain_client_with_roots(
            honest_bpas, honest_wpas
        )
        neuron = MagicMock()
        neuron.uid = 0
        neuron.wallet = MagicMock()
        neuron.metagraph.n.item.return_value = 3
        neuron.metagraph.validator_permit = [
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
            MagicMock(item=MagicMock(return_value=True)),
        ]
        neuron.metagraph.hotkeys = ["self", "bad", "good"]
        neuron.metagraph.axons = [
            MagicMock(ip="10.0.0.1", port=8421),
            MagicMock(ip="1.2.3.4", port=8421),
            MagicMock(ip="5.6.7.8", port=8421),
        ]
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=neuron,
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "dd" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-1"], purchase_ids={"sig-1": 5}
        )

        calls: list[str] = []

        class FakeRespBad:
            status_code = 200

            def json(self):
                return {"bpas": [1], "wpas": [1], "bpa_mode": False}

        class FakeRespGood:
            status_code = 200

            def json(self):
                return {
                    "bpas": honest_bpas,
                    "wpas": honest_wpas,
                    "bpa_mode": False,
                }

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                calls.append(url)
                if "1.2.3.4" in url:
                    return FakeRespBad()
                return FakeRespGood()

        with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
            "djinn_validator.api.middleware.create_signed_headers",
            return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
        ):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 1
        assert len(calls) == 2
        rec = ledger.get(signal_id="sig-1", buyer_address=idiot)
        assert rec is not None
        assert rec.bpas == honest_bpas

    @pytest.mark.asyncio
    async def test_prefetch_skips_legacy_zero_root_purchase(self) -> None:
        """A pre-V6 purchase has no on-chain root; we cannot verify, so
        do NOT accept peer data for it. Ledger stays empty."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        chain_client = MagicMock()
        chain_client.get_purchase_vector_roots = AsyncMock(
            return_value=(b"\x00" * 32, b"\x00" * 32)
        )
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "ee" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-legacy"], purchase_ids={"sig-legacy": 3}
        )

        class _NeverCalled:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):  # pragma: no cover
                raise AssertionError("peer should not be polled for a legacy purchase")

        with patch("httpx.AsyncClient", lambda **kw: _NeverCalled()):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0
        assert ledger.get(signal_id="sig-legacy", buyer_address=idiot) is None

    @pytest.mark.asyncio
    async def test_prefetch_skips_signal_with_zero_purchase_id(self) -> None:
        """Audit signal missing ``purchase_id`` (e.g., mis-bootstrapped
        v1 row). We have no pid to look up, so we cannot authenticate
        peer data. Skip rather than accept unverified bytes."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        chain_client = MagicMock()
        chain_client.get_purchase_vector_roots = AsyncMock()
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "ff" * 20
        audit_set = self._helpers._make_audit_set(idiot, ["sig-nopid"])

        class _NeverCalled:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):  # pragma: no cover
                raise AssertionError("peer should not be polled without pid")

        with patch("httpx.AsyncClient", lambda **kw: _NeverCalled()):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0
        chain_client.get_purchase_vector_roots.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prefetch_handles_root_rpc_failure(self) -> None:
        """If the on-chain root RPC fails (returns None), skip the
        signal rather than accepting peer data unverifiable."""
        from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
        from unittest.mock import patch

        coord = MPCCoordinator()
        chain_client = MagicMock()
        chain_client.get_purchase_vector_roots = AsyncMock(return_value=None)
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=self._helpers._make_neuron_with_one_peer(),
            chain_client=chain_client,
        )
        ledger = PurchaseOddsLedger()
        idiot = "0x" + "11" * 20
        audit_set = self._helpers._make_audit_set(
            idiot, ["sig-rpc-fail"], purchase_ids={"sig-rpc-fail": 9}
        )

        class _NeverCalled:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):  # pragma: no cover
                raise AssertionError("peer should not be polled when root RPC failed")

        with patch("httpx.AsyncClient", lambda **kw: _NeverCalled()):
            n = await orch._prefetch_missing_purchase_odds_from_peers(
                audit_set=audit_set, purchase_odds_ledger=ledger
            )
        assert n == 0


class TestPreMpcHasVotedGate:
    """v1699: pre-MPC hasVoted gate skips MPC compute when this validator has
    already voted on the canonical batchKey.

    UID 1 metrics pre-fix: 16 of 21 completed shadow_settles ended at
    preflight_already_voted in submit-from-shadow — 16 expensive MPC runs
    computed a vote that submit_vote then discarded. The gate detects this at
    the entry to the MPC compute box and saves the compute. Stale-snapshot is
    handled inside has_voted_for_batch (returns False, False so we re-vote on
    a new syncNonce).
    """

    def test_audit_set_store_passed_to_orchestrator_init(self) -> None:
        """The constructor must accept audit_set_store as a keyword arg.

        main.py:567 passes audit_set_store=audit_set_store at orchestrator
        construction so the pre-MPC pre_final branch can mark_settled and
        prevent the audit_set from bouncing on every subsequent cycle.
        Without the kwarg this would silently default to None and the
        cleanup never happens.
        """
        coord = MPCCoordinator()
        sentinel = object()
        orch = MPCOrchestrator(
            coordinator=coord,
            neuron=None,
            audit_set_store=sentinel,
        )
        assert orch._audit_set_store is sentinel

    def test_audit_set_store_defaults_to_none(self) -> None:
        """Backward-compat: omitting audit_set_store keeps prior behavior.

        Tests that constructed MPCOrchestrator without the new kwarg should
        still pass — pre-MPC pre_final branch then no-ops on mark_settled
        and falls back to post-MPC pre_final cleanup (status quo).
        """
        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord, neuron=None)
        assert orch._audit_set_store is None

    def test_pre_mpc_outcome_labels_registered_in_metrics(self) -> None:
        """The two new outcome labels must register on SHADOW_SETTLE_OUTCOME.

        Operators read /metrics to understand which gate fires; if the labels
        aren't registered the counter line won't appear at all and the gate
        is invisible. ``.labels(outcome=...)`` creates the child Counter on
        first access; this test makes sure access doesn't raise.
        """
        from djinn_validator.api.metrics import SHADOW_SETTLE_OUTCOME

        # First access creates the child; second access must read same.
        c1 = SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_pre_mpc_already_voted")
        c2 = SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_pre_mpc_finalized")
        assert c1 is SHADOW_SETTLE_OUTCOME.labels(
            outcome="abstain_pre_mpc_already_voted"
        )
        assert c2 is SHADOW_SETTLE_OUTCOME.labels(
            outcome="abstain_pre_mpc_finalized"
        )
