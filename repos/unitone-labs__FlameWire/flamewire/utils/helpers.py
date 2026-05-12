# The MIT License (MIT)
# Copyright © 2026 UnitOne Labs

import hashlib
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, TypeVar, Iterator, Tuple, Callable

import bittensor as bt

from flamewire.gateway import Node, MinerNode, CheckStats, ReferenceBlock, SYSTEM_EVENTS_KEY

T = TypeVar("T")


def batched(items: List[T], batch_size: int) -> Iterator[List[T]]:
    """
    Split a list into batches of specified size.

    Args:
        items: List of items to batch
        batch_size: Maximum size of each batch

    Yields:
        Lists of items, each with at most batch_size elements
    """
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def build_miner_nodes(
    nodes_by_hotkey: Dict[str, List[Node]],
) -> List[MinerNode]:
    """
    Build a list of MinerNode objects from gateway node lookup.

    Args:
        nodes_by_hotkey: Dict mapping miner hotkey to list of Node objects

    Returns:
        List of MinerNode objects initialized with empty local health stats
    """
    miner_nodes = []
    for hotkey, nodes in nodes_by_hotkey.items():
        for node in nodes:
            miner_nodes.append(MinerNode(
                miner_hotkey=hotkey,
                node_id=node.id,
                region=node.region,
                health=CheckStats(total=0, passed=0),
            ))

    return miner_nodes


def get_random_blocks(current_block: int) -> Tuple[int, int, int]:
    """
    Get random blocks from three intervals (old, middle, new).

    Args:
        current_block: The current block number

    Returns:
        Tuple of (old_block, middle_block, new_block)
    """
    interval_size = current_block // 3

    old_block = random.randint(0, interval_size - 1)
    middle_block = random.randint(interval_size, 2 * interval_size - 1)
    new_block = random.randint(2 * interval_size, current_block - 1)

    return old_block, middle_block, new_block


def verify_node_data(
    node: MinerNode,
    reference_blocks: List[ReferenceBlock],
    rpc_call_fn,
    network_head: int,
) -> Tuple[bool, List[int], int, int]:
    """
    Verify a miner node's data against reference blocks.

    Args:
        node: The miner node to verify
        reference_blocks: List of reference blocks to check against
        rpc_call_fn: Function to make RPC calls (gateway.rpc_call)

    Returns:
        Tuple of (passed, latencies, health_passed, health_total)
    """
    latencies = []
    health_passed = 0
    health_total = 0
    passed = True

    for ref_block in reference_blocks:
        health_total += 1
        try:
            # Health check: node must be synced and at network head.
            health_response = rpc_call_fn(
                "system_health",
                node.node_id,
                node.region,
                [],
            )
            header_response = rpc_call_fn(
                "chain_getHeader",
                node.node_id,
                node.region,
                [],
            )
            if not health_response.is_error() and not header_response.is_error():
                health_result = health_response.result or {}
                header_result = header_response.result or {}
                is_syncing = bool(health_result.get("isSyncing", True))
                node_head_hex = header_result.get("number")
                node_head = int(node_head_hex, 16) if isinstance(node_head_hex, str) else None
                # Compare against the validator snapshot head captured at cycle start.
                # Nodes can naturally advance beyond that value while checks are running.
                if (not is_syncing) and (node_head is not None) and (node_head >= network_head):
                    health_passed += 1

            # Get events data from the miner's node
            response = rpc_call_fn(
                "state_getStorage",
                node.node_id,
                node.region,
                [SYSTEM_EVENTS_KEY, ref_block.block_hash],
            )

            # Collect latency if available
            if response.latency_ms is not None:
                latencies.append(response.latency_ms)

            if response.is_error():
                bt.logging.warning(
                    f"Node {node.node_id} RPC error on block {ref_block.block_number}: {response.error.message}"
                )
                passed = False
                continue

            # Hash the raw data
            raw_data = response.result or ""
            events_hash = hashlib.sha256(raw_data.encode()).hexdigest()

            # Compare with reference
            if events_hash != ref_block.events_hash:
                bt.logging.warning(
                    f"Node {node.node_id} hash mismatch on block {ref_block.block_number} "
                    f"({ref_block.verification_type}): expected {ref_block.events_hash[:16]}... got {events_hash[:16]}..."
                )
                passed = False

        except Exception as e:
            bt.logging.warning(f"Node {node.node_id} verification error: {e}")
            passed = False

    return passed, latencies, health_passed, health_total


def verify_all_nodes(
    miner_nodes: List[MinerNode],
    reference_blocks: List[ReferenceBlock],
    rpc_call_fn: Callable,
    network_head: int,
    max_workers: int = 32,
) -> Tuple[int, int]:
    """
    Verify all miner nodes against reference blocks in parallel.

    Args:
        miner_nodes: List of miner nodes to verify
        reference_blocks: List of reference blocks to check against
        rpc_call_fn: Function to make RPC calls (gateway.rpc_call)
        network_head: Current chain head from validator reference endpoint
        max_workers: Maximum number of concurrent verifications

    Returns:
        Tuple of (verified_count, failed_count)
    """
    if not miner_nodes or not reference_blocks:
        return 0, 0

    verified_count = 0
    failed_count = 0

    def verify_single_node(node: MinerNode) -> Tuple[MinerNode, bool, List[int], int, int]:
        passed, latencies, health_passed, health_total = verify_node_data(
            node,
            reference_blocks,
            rpc_call_fn,
            network_head=network_head,
        )
        return node, passed, latencies, health_passed, health_total

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(verify_single_node, node): node for node in miner_nodes}

        for future in as_completed(futures):
            try:
                node, passed, latencies, health_passed, health_total = future.result()
                node.data_verified = passed
                node.health = CheckStats(total=health_total, passed=health_passed)

                # Calculate average latency
                if latencies:
                    node.avg_latency_ms = sum(latencies) / len(latencies)

                if passed:
                    verified_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                node = futures[future]
                node.data_verified = False
                failed_count += 1
                bt.logging.error(f"Node {node.node_id} verification failed with exception: {e}")

    return verified_count, failed_count
