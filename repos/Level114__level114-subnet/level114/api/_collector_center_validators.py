from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

import bittensor as bt

from level114.types import ValidatorServer


class _ValidatorEndpointsMixin:
    """Validator and server lookup helpers."""

    def _fetch_validator_server_ids_chunk(
        self,
        hotkeys_chunk: List[str],
        timeout: float,
        chunk_index: int,
        total_chunks: int,
    ) -> Tuple[int, List[ValidatorServer]]:
        if not hotkeys_chunk:
            return 400, []

        query = urlencode({"hotkeys": ",".join(hotkeys_chunk)})
        url = f"{self.base_url}/validators/servers/ids?{query}"
        req = Request(url, headers=self.default_headers(), method="GET")

        try:
            with urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                body = resp.read().decode("utf-8", errors="ignore")
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    if status < 200 or status >= 300:
                        bt.logging.error(
                            f"collector ids chunk={chunk_index}/{total_chunks} status={status} body={body}"
                        )
                    return status, []

                items_raw = data.get("items", []) if isinstance(data, dict) else []
                items: List[ValidatorServer] = []
                for item in items_raw:
                    if isinstance(item, dict):
                        vid = str(item.get("id", ""))
                        hk = str(item.get("hotkey", ""))
                        reg = item.get("registered_at")
                        if vid and hk:
                            items.append(ValidatorServer(id=vid, hotkey=hk, registered_at=reg))

                if status < 200 or status >= 300:
                    bt.logging.error(
                        f"collector ids chunk={chunk_index}/{total_chunks} status={status} body={body}"
                    )
                return status, items
        except HTTPError as e:
            bt.logging.error(
                f"collector ids chunk={chunk_index}/{total_chunks} error: HTTP {e.code} - {e.reason}"
            )
            return e.code, []
        except Exception as e:  # noqa: BLE001
            bt.logging.error(
                f"collector ids chunk={chunk_index}/{total_chunks} error: {e}"
            )
            return 599, []

    def get_validator_server_ids(
        self, hotkeys: List[str], timeout_seconds: Optional[float] = None
    ) -> Tuple[int, List[ValidatorServer]]:
        if not hotkeys:
            return 400, []

        unique_hotkeys = list(dict.fromkeys(hotkeys))

        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds

        max_chunks = 5
        chunk_count = min(max_chunks, len(unique_hotkeys)) or 1
        chunk_size = max(1, (len(unique_hotkeys) + chunk_count - 1) // chunk_count)
        total_chunks = (len(unique_hotkeys) + chunk_size - 1) // chunk_size

        aggregated: List[ValidatorServer] = []
        seen_pairs: Set[Tuple[str, str]] = set()
        first_error_status: Optional[int] = None
        any_success = False

        for idx in range(0, len(unique_hotkeys), chunk_size):
            chunk_index = (idx // chunk_size) + 1
            chunk_hotkeys = unique_hotkeys[idx : idx + chunk_size]
            status, items = self._fetch_validator_server_ids_chunk(
                chunk_hotkeys,
                timeout,
                chunk_index,
                total_chunks,
            )

            if first_error_status is None and (status < 200 or status >= 300):
                first_error_status = status
            if 200 <= status < 300:
                any_success = True

            for item in items:
                pair = (item.hotkey, item.id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                aggregated.append(item)

        if aggregated or any_success:
            return (first_error_status or 200), aggregated

        return (first_error_status or 599), []

    def get_validator_server_ids_map(
        self, hotkeys: List[str], timeout_seconds: Optional[float] = None
    ) -> Tuple[int, Dict[str, List[ValidatorServer]]]:
        status, items = self.get_validator_server_ids(hotkeys, timeout_seconds)
        mapping: Dict[str, List[ValidatorServer]] = {}
        for item in items:
            mapping.setdefault(item.hotkey, []).append(item)
        return status, mapping

    def get_server_mappings(
        self, hotkeys: List[str], timeout_seconds: Optional[float] = None
    ) -> Tuple[int, Dict[str, List[Dict[str, Any]]]]:
        status, mapping = self.get_validator_server_ids_map(hotkeys, timeout_seconds)
        result: Dict[str, List[Dict[str, Any]]] = {}
        for hotkey, validator_servers in mapping.items():
            if not isinstance(validator_servers, list):
                continue
            servers_payload: List[Dict[str, Any]] = []
            for validator_server in validator_servers:
                servers_payload.append(
                    {
                        "server_id": validator_server.id,
                        "hotkey": validator_server.hotkey,
                        "registered_at": validator_server.registered_at,
                    }
                )
            if servers_payload:
                result[hotkey] = servers_payload
        return status, result
