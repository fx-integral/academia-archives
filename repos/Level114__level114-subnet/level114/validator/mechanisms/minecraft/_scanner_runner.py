"""Helper to execute Minecraft scanner catalog refreshes."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Set

from level114.validator.mechanisms.minecraft.server_scanner import (
    SCANNER_TIMEOUT,
    scan_catalog,
)
from level114.validator.mechanisms.minecraft._scanner_logger import _BTScannerLogger


def perform_scan(
    collector_api: Any,
    logger: _BTScannerLogger,
    server_ids: Set[str],
) -> Dict[str, Any]:
    status, servers = collector_api.get_active_servers()
    now = time.time()
    results: Dict[str, Optional[Dict[str, Any]]] = {sid: None for sid in server_ids}
    attempted: Set[str] = set()
    missing: Set[str] = set(server_ids)
    metrics = {"total_elapsed": 0.0, "avg_per_server": 0.0, "per_scanner": {}, "retries": {}}
    error: Optional[str] = None

    if status < 200 or status >= 300:
        logger.error(f"Collector /servers returned status {status}")
        error = f"status_{status}"
        return {
            "results": results,
            "attempted": attempted,
            "missing": missing,
            "metrics": metrics,
            "timestamp": now,
            "error": error,
        }

    feed_map: Dict[str, Dict[str, Any]] = {
        str(item.get("id")): item
        for item in servers
        if isinstance(item, dict) and item.get("id")
    }

    attempted = {sid for sid in server_ids if sid in feed_map}
    missing = set(server_ids) - attempted

    if not attempted:
        logger.warning(
            f"No matching servers present in collector feed (requested={len(server_ids)})"
        )
        return {
            "results": results,
            "attempted": attempted,
            "missing": missing,
            "metrics": metrics,
            "timestamp": now,
            "error": None,
        }

    catalog: Dict[str, Optional[int]] = {}
    address_map: Dict[str, str] = {}
    duplicates: Set[str] = set()

    for server_id in attempted:
        feed_info = feed_map.get(server_id, {})
        host = str(feed_info.get("ip") or feed_info.get("hostname") or "").strip()
        port = feed_info.get("port")
        if not host or port is None:
            logger.warning(
                f"Missing network coordinates for server {server_id} (host={host!r}, port={port!r})"
            )
            missing.add(server_id)
            continue

        address = f"{host}:{int(port)}"
        if address in address_map:
            logger.warning(
                f"Duplicate address {address} for servers {address_map[address]} and {server_id}"
            )
            duplicates.add(server_id)
            continue

        address_map[address] = server_id
        catalog[address] = feed_info.get("active_players")
        results[server_id] = {
            "address": address,
            "online": False,
            "players": 0,
            "max_players": 0,
            "ping": 0.0,
            "scanner": None,
            "scan_timestamp": now,
            "feed_active_players": feed_info.get("active_players"),
            "feed_max_players": feed_info.get("max_players"),
            "hostname": host,
            "port": int(port),
            "hotkey": feed_info.get("hotkey"),
        }

    if duplicates:
        missing.update(duplicates)

    disabled_scanners_cycle: Set[str] = set()

    if catalog:
        scan_results, metrics, disabled_scanners_cycle = scan_catalog(
            catalog,
            logger,
            timeout=SCANNER_TIMEOUT,
        )
        for entry in scan_results:
            address = entry.get("address")
            if not address:
                continue
            server_id = address_map.get(address)
            if not server_id:
                continue
            feed_info = feed_map.get(server_id, {})
            merged = dict(entry)
            merged.update(
                {
                    "server_id": server_id,
                    "scan_timestamp": now,
                    "feed_active_players": feed_info.get("active_players"),
                    "feed_max_players": feed_info.get("max_players"),
                    "hostname": feed_info.get("hostname") or feed_info.get("ip"),
                    "port": feed_info.get("port"),
                    "hotkey": feed_info.get("hotkey"),
                }
            )
            results[server_id] = merged

    return {
        "results": results,
        "attempted": attempted - duplicates,
        "missing": missing,
        "metrics": metrics,
        "timestamp": now,
        "error": error,
        "disabled_scanners": sorted(disabled_scanners_cycle),
    }
