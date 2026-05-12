"""Helpers for fetching Minecraft server mappings from collector API."""

from __future__ import annotations

import time
from typing import Dict, List

import bittensor as bt


def fetch_server_mappings(mechanism, hotkeys: List[str]) -> Dict[str, List[str]]:
    cached = mechanism.server_ids_last_fetch
    now = time.time()

    if cached and (now - cached) < mechanism.server_ids_min_refresh_interval:
        return {hk: list(ids) for hk, ids in mechanism.hotkey_to_server_ids.items()}

    try:
        status, mappings = mechanism.collector_api.get_server_mappings(hotkeys)
        if status != 200 or not isinstance(mappings, dict):
            bt.logging.debug(
                f"[Minecraft] Failed to refresh server mappings (status={status});"
                f" using cached data with {len(mechanism.hotkey_to_server_ids)} hotkeys"
            )
            return {hk: list(ids) for hk, ids in mechanism.hotkey_to_server_ids.items()}

        mechanism.server_ids_last_fetch = now
        hotkey_to_server_ids: Dict[str, List[str]] = {}
        server_id_to_hotkey: Dict[str, str] = {}
        for hotkey, entries in mappings.items():
            if not isinstance(entries, list):
                continue
            collected_ids: List[str] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                server_id = entry.get("server_id")
                if not server_id:
                    continue
                collected_ids.append(server_id)
                server_id_to_hotkey[server_id] = hotkey
            if collected_ids:
                hotkey_to_server_ids[hotkey] = collected_ids

        mechanism.hotkey_to_server_ids = hotkey_to_server_ids
        mechanism.server_id_to_hotkey = server_id_to_hotkey
        return {hk: list(ids) for hk, ids in mechanism.hotkey_to_server_ids.items()}

    except Exception as exc:  # noqa: BLE001
        bt.logging.error(f"[Minecraft] Error fetching server mappings: {exc}")
        return {hk: list(ids) for hk, ids in mechanism.hotkey_to_server_ids.items()}
