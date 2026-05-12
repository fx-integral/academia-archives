import hashlib
import unittest

from flamewire.gateway.types import CheckStats, MinerNode, RPCResponse, ReferenceBlock
from flamewire.utils.helpers import verify_node_data


def _rpc_ok(result=None, latency_ms=None):
    return RPCResponse(jsonrpc="2.0", id=1, result=result, error=None, latency_ms=latency_ms)


class TestVerificationHealthAccounting(unittest.TestCase):
    def test_uptime_counts_only_health_passes(self):
        node = MinerNode(
            miner_hotkey="miner_a",
            node_id="node_1",
            region="us",
            health=CheckStats(total=0, passed=0),
        )
        raw_events = "0xdeadbeef"
        events_hash = hashlib.sha256(raw_events.encode()).hexdigest()
        reference_blocks = [
            ReferenceBlock(
                block_number=100,
                block_hash="0xabc",
                verification_type="old",
                events_data_size=len(raw_events),
                events_hash=events_hash,
            ),
            ReferenceBlock(
                block_number=200,
                block_hash="0xdef",
                verification_type="new",
                events_data_size=len(raw_events),
                events_hash=events_hash,
            ),
        ]

        def rpc_call(method, _node_id, _region, _params):
            if method == "system_health":
                return _rpc_ok({"isSyncing": False})
            if method == "chain_getHeader":
                return _rpc_ok({"number": hex(999)})
            if method == "state_getStorage":
                return _rpc_ok(raw_events, latency_ms=42)
            raise AssertionError(f"Unexpected RPC method: {method}")

        passed, latencies, health_passed, health_total = verify_node_data(
            node=node,
            reference_blocks=reference_blocks,
            rpc_call_fn=rpc_call,
            network_head=999,
        )

        self.assertTrue(passed)
        self.assertEqual(health_total, 2)
        self.assertEqual(health_passed, 2)
        self.assertEqual(latencies, [42, 42])

    def test_successful_data_request_does_not_inflate_uptime(self):
        node = MinerNode(
            miner_hotkey="miner_a",
            node_id="node_2",
            region="eu",
            health=CheckStats(total=0, passed=0),
        )
        raw_events = "0xcafebabe"
        events_hash = hashlib.sha256(raw_events.encode()).hexdigest()
        reference_blocks = [
            ReferenceBlock(
                block_number=300,
                block_hash="0x123",
                verification_type="middle",
                events_data_size=len(raw_events),
                events_hash=events_hash,
            )
        ]

        def rpc_call(method, _node_id, _region, _params):
            if method == "system_health":
                # Health fails because node is still syncing.
                return _rpc_ok({"isSyncing": True})
            if method == "chain_getHeader":
                return _rpc_ok({"number": hex(500)})
            if method == "state_getStorage":
                # Data can still be returned correctly, but uptime must remain 0/1.
                return _rpc_ok(raw_events, latency_ms=15)
            raise AssertionError(f"Unexpected RPC method: {method}")

        passed, _latencies, health_passed, health_total = verify_node_data(
            node=node,
            reference_blocks=reference_blocks,
            rpc_call_fn=rpc_call,
            network_head=500,
        )

        self.assertTrue(passed)
        self.assertEqual(health_total, 1)
        self.assertEqual(health_passed, 0)

    def test_node_ahead_of_snapshot_head_counts_as_healthy(self):
        node = MinerNode(
            miner_hotkey="miner_a",
            node_id="node_3",
            region="as",
            health=CheckStats(total=0, passed=0),
        )
        raw_events = "0x00"
        events_hash = hashlib.sha256(raw_events.encode()).hexdigest()
        reference_blocks = [
            ReferenceBlock(
                block_number=400,
                block_hash="0x456",
                verification_type="new",
                events_data_size=len(raw_events),
                events_hash=events_hash,
            )
        ]

        def rpc_call(method, _node_id, _region, _params):
            if method == "system_health":
                return _rpc_ok({"isSyncing": False})
            if method == "chain_getHeader":
                # Node advanced while cycle is running.
                return _rpc_ok({"number": hex(101)})
            if method == "state_getStorage":
                return _rpc_ok(raw_events, latency_ms=10)
            raise AssertionError(f"Unexpected RPC method: {method}")

        passed, _latencies, health_passed, health_total = verify_node_data(
            node=node,
            reference_blocks=reference_blocks,
            rpc_call_fn=rpc_call,
            network_head=100,
        )

        self.assertTrue(passed)
        self.assertEqual(health_total, 1)
        self.assertEqual(health_passed, 1)


if __name__ == "__main__":
    unittest.main()
