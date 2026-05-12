import json
from typing import Any, List, Optional
from pydantic import TypeAdapter
import httpx
import asyncio

from fiber.logging_utils import get_logger

from fiber.chain.metagraph import Metagraph as BaseMetagraph
from fiber.chain import fetch_nodes

from subnet_validator.fiber_ext.node import ExtendedNode
from subnet_validator import dependencies
from subnet_validator import APP_TITLE


logger = get_logger(__name__)


class ExtendedMetagraph(BaseMetagraph):
    """Metagraph subclass that enriches nodes and uses a configurable nodes file path."""

    def sync_nodes(self) -> None:
        logger.info("Syncing nodes (extended)...")
        assert (
            self.substrate is not None
        ), "Substrate interface is not initialized"
        nodes = fetch_nodes._get_nodes_for_uid(self.substrate, self.netuid)

        # Enrich nodes with local fields if present in saved file or defaults
        enriched: dict[str, ExtendedNode] = {}

        # Build ExtendedNode objects first
        exts: list[ExtendedNode] = [
            ExtendedNode(**n.model_dump()) for n in nodes
        ]

        # Fetch versions concurrently
        versions: dict[str, tuple[str | None, bool]] = asyncio.run(
            self._fetch_versions_concurrently(exts)
        )

        for ext in exts:
            version, is_validator = versions.get(ext.hotkey, (None, False))
            ext.version = version
            ext.is_validator = is_validator
            enriched[ext.hotkey] = ext

        self.nodes = enriched
        logger.info(
            f"✅ Successfully synced {len(self.nodes)} nodes (extended)!"
        )

    # Override save/load to use custom path from settings
    def save_nodes(self) -> None:
        settings = dependencies.get_settings()
        nodes_file = settings.nodes_file

        logger.info(f"Saving {len(self.nodes)} nodes to {nodes_file}")

        if len(self.nodes) == 0:
            logger.warning("No nodes to save!")
            return

        # Use Pydantic v2 TypeAdapter to serialize dict[str, ExtendedNode]
        adapter = TypeAdapter(dict[str, ExtendedNode])
        json_bytes = adapter.dump_json(self.nodes)
        with open(nodes_file, "w") as f:
            f.write(json_bytes.decode("utf-8"))

    def load_nodes(self) -> None:
        """Load nodes using Pydantic v2 into ExtendedNode instances."""
        loaded = self._load_nodes_pydantic()
        if not loaded:
            return
        self.nodes = loaded

    # Removed fallback raw loader; Pydantic loader is sufficient with defaults

    def _load_nodes_pydantic(self) -> dict[str, ExtendedNode]:
        settings = dependencies.get_settings()
        nodes_file = settings.nodes_file
        logger.info(f"Loading nodes from {nodes_file} via Pydantic")
        try:
            with open(nodes_file, "r") as f:
                content = f.read()
            adapter = TypeAdapter(dict[str, ExtendedNode])
            return adapter.validate_json(content)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(
                f"Error loading nodes from {nodes_file}: {e}  - will resync manually"
            )
            return {}

    async def _fetch_version_and_role(
        self, client: httpx.AsyncClient, node: ExtendedNode
    ) -> tuple[str | None, bool]:
        ip = node.ip
        port = node.port
        if ip == "0.0.0.0":
            return None, False
        url = f"http://{ip}:{port}/openapi.json"
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None, False
            data: dict = resp.json()
            info: dict = data.get("info", {})
            title = info.get("title")
            version = info.get("version")
            return version, title == APP_TITLE
        except Exception:
            return None, False

    async def _fetch_versions_concurrently(
        self, nodes: list[ExtendedNode]
    ) -> dict[str, tuple[str | None, bool]]:
        # Bound concurrency to avoid overload
        settings = dependencies.get_settings()
        max_concurrent = settings.max_concurrent_version_requests
        semaphore = asyncio.Semaphore(max_concurrent)

        async with httpx.AsyncClient(timeout=10) as client:

            async def task(
                node: ExtendedNode,
            ) -> tuple[str, tuple[str | None, bool]]:
                async with semaphore:
                    result = await self._fetch_version_and_role(client, node)
                    return node.hotkey, result

            results = await asyncio.gather(
                *(task(n) for n in nodes), return_exceptions=False
            )
            return {hk: res for hk, res in results}

    def get_miner_nodes(self) -> List[ExtendedNode]:
        """Get all miner nodes (nodes where is_validator=False)."""
        return [
            node
            for node in self.nodes.values()
            if not getattr(node, "is_validator", False)
        ]

    def get_validator_nodes(self) -> List[ExtendedNode]:
        """Get all validator nodes (nodes where is_validator=True)."""
        return [
            node
            for node in self.nodes.values()
            if getattr(node, "is_validator", False)
        ]

    def get_node_by_hotkey(self, hotkey: str) -> Optional[ExtendedNode]:
        """Get a specific node by its hotkey."""
        return self.nodes.get(hotkey)
