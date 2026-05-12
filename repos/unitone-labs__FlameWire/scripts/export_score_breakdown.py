#!/usr/bin/env python3
# The MIT License (MIT)
# Copyright © 2026 UnitOne Labs

import argparse
import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import List

import bittensor as bt

# Ensure repo root imports work when running from scripts/.
REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from flamewire.gateway import GatewayClient, RpcClient, SubtensorRpcTransport
from flamewire.utils.helpers import (
    batched,
    build_miner_nodes,
    get_random_blocks,
    verify_all_nodes,
)
from flamewire.utils.metagraph import get_miner_hotkeys
from flamewire.utils.scoring import (
    SUPPORTED_REGIONS,
    calculate_miner_scores,
    calculate_node_scores,
    scores_to_weights,
)


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def avg(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one verification/scoring pass and export per-region score breakdown per miner."
    )
    parser.add_argument("--env-file", type=str, default="", help="Env file path. Defaults to .env, then .env.example.")
    parser.add_argument("--netuid", type=int, default=97, help="Subnet netuid.")
    parser.add_argument(
        "--subtensor-network",
        type=str,
        default="",
        help="Subtensor network endpoint/name. Defaults to SUBTENSOR_NETWORK env var.",
    )
    parser.add_argument(
        "--gateway-url",
        type=str,
        default="",
        help="Gateway base URL. Defaults to GATEWAY_URL env var.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="",
        help="Validator API key. Defaults to VALIDATOR_API_KEY env var.",
    )
    parser.add_argument(
        "--reference-rpc-url",
        type=str,
        default="",
        help="Archive-capable reference RPC endpoint. Defaults to REFERENCE_RPC_URL then SUBTENSOR_NETWORK.",
    )
    parser.add_argument("--max-workers", type=int, default=32, help="Parallel workers for node verification.")
    parser.add_argument("--json-out", type=str, default="score_breakdown_latest.json", help="JSON report output path.")
    parser.add_argument("--csv-out", type=str, default="score_breakdown_latest.csv", help="CSV report output path.")
    parser.add_argument("--top", type=int, default=20, help="How many top miners to print to stdout.")
    parser.add_argument(
        "--node-preview",
        type=int,
        default=20,
        help="How many top node performance rows to print to stdout.",
    )
    parser.add_argument(
        "--failed-preview",
        type=int,
        default=20,
        help="How many failed nodes to print to stdout.",
    )
    parser.add_argument(
        "--include-zero",
        action="store_true",
        help="Include zero-weight miners in stdout preview (all miners are always present in output files).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.env_file:
        env_path = Path(args.env_file)
    elif Path(".env").exists():
        env_path = Path(".env")
    else:
        env_path = Path(".env.example")
    load_env_file(env_path)

    api_key = args.api_key or os.getenv("VALIDATOR_API_KEY", "")
    if not api_key:
        raise SystemExit("VALIDATOR_API_KEY is missing. Provide --api-key or set it in env.")

    subtensor_network = args.subtensor_network or os.getenv(
        "SUBTENSOR_NETWORK",
        "wss://entrypoint-finney.opentensor.ai:443",
    )
    gateway_url = args.gateway_url or os.getenv("GATEWAY_URL", "https://gateway-dev.flamewire.io")
    reference_rpc_url = (
        args.reference_rpc_url
        or os.getenv("REFERENCE_RPC_URL", "")
        or subtensor_network
    )
    max_workers = int(os.getenv("VALIDATOR_MAX_WORKERS", str(args.max_workers)))
    netuid = int(os.getenv("NETUID", str(args.netuid)))

    bt.logging.enable_default()
    bt.logging.set_warning(True)
    bt.logging.info(
        f"Running score breakdown for netuid={netuid}, subtensor={subtensor_network}, gateway={gateway_url}, reference_rpc={reference_rpc_url}"
    )

    subtensor = bt.Subtensor(network=subtensor_network)
    metagraph = subtensor.metagraph(netuid=netuid, lite=False)

    # Use -1 as validator UID to include all miner-like neurons.
    miner_hotkeys = get_miner_hotkeys(metagraph, -1)
    if not miner_hotkeys:
        raise SystemExit("No miner hotkeys found in metagraph.")

    gateway = GatewayClient(api_key=api_key, base_url=gateway_url)
    rpc = RpcClient(SubtensorRpcTransport(reference_rpc_url))

    all_nodes = {}
    for batch in batched(miner_hotkeys, 100):
        all_nodes.update(gateway.lookup_nodes(batch))

    miner_nodes = build_miner_nodes(all_nodes)
    if not miner_nodes:
        raise SystemExit("No miner nodes returned by gateway.")

    nodes_per_region = defaultdict(int)
    for node in miner_nodes:
        nodes_per_region[node.region] += 1
    print(
        "Verification scope: "
        f"{len(miner_hotkeys)} miners, {len(miner_nodes)} nodes "
        f"(us={nodes_per_region.get('us', 0)}, eu={nodes_per_region.get('eu', 0)}, as={nodes_per_region.get('as', 0)})"
    )

    current_block = rpc.get_current_block()
    old_block, middle_block, new_block = get_random_blocks(current_block)
    reference_blocks = []
    for block_num, verification_type in [
        (old_block, "old"),
        (middle_block, "middle"),
        (new_block, "new"),
    ]:
        ref_block = rpc.get_reference_block(block_num, verification_type)
        if ref_block:
            reference_blocks.append(ref_block)
    if not reference_blocks:
        raise SystemExit("No reference blocks available for correctness validation.")

    print("Reference checks:")
    for ref in reference_blocks:
        print(
            f"  [{ref.verification_type}] block={ref.block_number} "
            f"hash={ref.block_hash[:18]}... events_size={ref.events_data_size} "
            f"events_hash={ref.events_hash[:18]}..."
        )

    verified_count, failed_count = verify_all_nodes(
        miner_nodes,
        reference_blocks,
        gateway.rpc_call,
        network_head=current_block,
        max_workers=max_workers,
    )
    bt.logging.info(f"Verification complete: passed={verified_count}, failed={failed_count}")
    print(
        f"Verification result: passed={verified_count}, failed={failed_count}, "
        f"pass_rate={(verified_count / max(len(miner_nodes), 1)):.2%}"
    )

    node_scores = calculate_node_scores(miner_nodes)
    miner_scores = calculate_miner_scores(node_scores)

    node_score_by_id = {score.node_id: score for score in node_scores}
    sorted_nodes = sorted(
        miner_nodes,
        key=lambda n: node_score_by_id.get(n.node_id).total if n.node_id in node_score_by_id else 0.0,
        reverse=True,
    )

    print("\nTop node performance:")
    preview_count = max(args.node_preview, 0)
    for node in sorted_nodes[:preview_count]:
        score = node_score_by_id.get(node.node_id)
        uptime = node.health.success_rate()
        latency_display = f"{node.avg_latency_ms:.2f}" if node.avg_latency_ms is not None else "n/a"
        correctness_display = "pass" if node.data_verified else "fail"
        score_total = score.total if score is not None else 0.0
        print(
            f"  {node.node_id} miner={node.miner_hotkey[:12]}... region={node.region} "
            f"correctness={correctness_display} uptime={node.health.passed}/{node.health.total} ({uptime:.2%}) "
            f"latency_ms={latency_display} node_score={score_total:.6f}"
        )

    failed_nodes = [node for node in miner_nodes if not node.data_verified]
    if failed_nodes:
        print("\nFailed nodes:")
        for node in failed_nodes[: max(args.failed_preview, 0)]:
            uptime = node.health.success_rate()
            latency_display = f"{node.avg_latency_ms:.2f}" if node.avg_latency_ms is not None else "n/a"
            score_total = node_score_by_id.get(node.node_id).total if node.node_id in node_score_by_id else 0.0
            print(
                f"  {node.node_id} miner={node.miner_hotkey[:12]}... region={node.region} "
                f"uptime={node.health.passed}/{node.health.total} ({uptime:.2%}) "
                f"latency_ms={latency_display} node_score={score_total:.6f}"
            )

    ordered_hotkeys = sorted(miner_hotkeys)
    weights = scores_to_weights(miner_scores, ordered_hotkeys)
    weight_by_hotkey = {hotkey: float(weight) for hotkey, weight in zip(ordered_hotkeys, weights)}
    miner_score_by_hotkey = {score.miner_hotkey: float(score.total) for score in miner_scores}
    miner_details_by_hotkey = {score.miner_hotkey: score for score in miner_scores}

    grouped = defaultdict(lambda: defaultdict(list))
    for score in node_scores:
        grouped[score.miner_hotkey][score.region].append(score)

    report_rows = []
    csv_rows = []

    for hotkey in ordered_hotkeys:
        miner_detail = miner_details_by_hotkey.get(hotkey)
        diversity_bonus = float(miner_detail.diversity_bonus) if miner_detail else 1.0
        regions_covered = int(miner_detail.regions_covered) if miner_detail else 0
        regional_sum_before_diversity = (
            float(sum(miner_detail.regions.values()))
            if miner_detail
            else 0.0
        )

        regions = {}
        for region in SUPPORTED_REGIONS:
            scores = grouped[hotkey][region]
            correctness = avg([s.correctness for s in scores])
            uptime = avg([s.uptime for s in scores])
            latency = avg([s.latency for s in scores])
            node_score_raw_avg = avg([s.total for s in scores])
            region_base_score = (
                float(miner_detail.region_base_scores.get(region, 0.0))
                if miner_detail
                else 0.0
            )
            region_multiplier = (
                float(miner_detail.region_multipliers.get(region, 0.0))
                if miner_detail
                else 0.0
            )
            region_score = (
                float(miner_detail.regions.get(region, 0.0))
                if miner_detail
                else 0.0
            )
            region_contribution_after_diversity = region_score * diversity_bonus

            region_node_details = [
                {
                    "node_id": s.node_id,
                    "correctness": float(s.correctness),
                    "uptime": float(s.uptime),
                    "latency": float(s.latency),
                    "node_score": float(s.total),
                }
                for s in scores
            ]

            regions[region] = {
                "node_count": len(scores),
                "correctness": float(correctness),
                "uptime": float(uptime),
                "latency": float(latency),
                "node_score_raw_avg": float(node_score_raw_avg),
                "region_base_score": float(region_base_score),
                "region_multiplier": float(region_multiplier),
                "region_score": float(region_score),
                "region_contribution_after_diversity": float(region_contribution_after_diversity),
                "nodes": region_node_details,
            }

            csv_rows.append(
                {
                    "hotkey": hotkey,
                    "region": region,
                    "node_count": len(scores),
                    "correctness": correctness,
                    "uptime": uptime,
                    "latency": latency,
                    "node_score_raw_avg": node_score_raw_avg,
                    "region_base_score": region_base_score,
                    "region_multiplier": region_multiplier,
                    "region_score": region_score,
                    "region_contribution_after_diversity": region_contribution_after_diversity,
                    "regions_covered": regions_covered,
                    "diversity_bonus": diversity_bonus,
                    "regional_sum_before_diversity": regional_sum_before_diversity,
                    "final_score": miner_score_by_hotkey.get(hotkey, 0.0),
                    "weight": weight_by_hotkey.get(hotkey, 0.0),
                }
            )

        report_rows.append(
            {
                "hotkey": hotkey,
                "regions_covered": regions_covered,
                "diversity_bonus": diversity_bonus,
                "regional_sum_before_diversity": float(regional_sum_before_diversity),
                "final_score": float(miner_score_by_hotkey.get(hotkey, 0.0)),
                "weight": float(weight_by_hotkey.get(hotkey, 0.0)),
                "regions": regions,
            }
        )

    report_rows.sort(key=lambda x: x["weight"], reverse=True)

    json_out = Path(args.json_out)
    csv_out = Path(args.csv_out)
    json_out.write_text(json.dumps(report_rows, indent=2))
    with csv_out.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "hotkey",
                "region",
                "node_count",
                "correctness",
                "uptime",
                "latency",
                "node_score_raw_avg",
                "region_base_score",
                "region_multiplier",
                "region_score",
                "region_contribution_after_diversity",
                "regions_covered",
                "diversity_bonus",
                "regional_sum_before_diversity",
                "final_score",
                "weight",
            ],
        )
        writer.writeheader()
        writer.writerows(csv_rows)

    preview_rows = report_rows
    if not args.include_zero:
        preview_rows = [r for r in report_rows if r["weight"] > 0]
    preview_rows = preview_rows[: args.top]

    print(f"Saved JSON report: {json_out}")
    print(f"Saved CSV report:  {csv_out}")
    print(f"Miners in report: {len(report_rows)}")
    print("Top miners:")
    for row in preview_rows:
        print(
            f"{row['hotkey']} final_score={row['final_score']:.8f} "
            f"weight={row['weight']:.8f} diversity_bonus={row['diversity_bonus']:.2f} "
            f"regions_covered={row['regions_covered']}"
        )
        for region in SUPPORTED_REGIONS:
            region_data = row["regions"][region]
            print(
                f"  [{region}] c={region_data['correctness']:.6f} "
                f"u={region_data['uptime']:.6f} l={region_data['latency']:.6f} "
                f"base={region_data['region_base_score']:.6f} "
                f"mult={region_data['region_multiplier']:.6f} "
                f"region_score={region_data['region_score']:.6f}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
