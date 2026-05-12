# The MIT License (MIT)
# Copyright © 2026 UnitOne Labs

import requests
from requests.adapters import HTTPAdapter
from typing import Optional, Dict, Any, List
import bittensor as bt

from .types import (
    GatewayError,
    GatewayAPIError,
    Node,
    CheckStats,
    NodeStatistics,
    RegionStats,
    StatisticsMeta,
    StatisticsResponse,
    RPCError,
    RPCResponse,
)


class GatewayClient:
    """
    Client for communicating with the FlameWire Gateway API.
    """

    def __init__(self, api_key: str, base_url: str):
        """
        Initialize the Gateway client.

        Args:
            api_key: API key for authentication
            base_url: Base URL of the gateway API
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
        })
        # Match validator concurrency to avoid connection-pool churn warnings under parallel checks.
        adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _handle_error_response(self, response: requests.Response) -> None:
        """Parse and raise gateway error if response is an error."""
        try:
            data = response.json()
            if "error" in data:
                error = GatewayError(
                    error=data.get("error", "Unknown"),
                    message=data.get("message", ""),
                    status=data.get("status", response.status_code),
                )
                raise GatewayAPIError(error)
        except ValueError:
            pass
        response.raise_for_status()

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Make a request to the gateway API.
        """
        url = f"{self.base_url}{endpoint}"

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=data,
                params=params,
                timeout=timeout,
            )
            if not response.ok:
                self._handle_error_response(response)
            return response.json() if response.text else {}
        except GatewayAPIError:
            raise
        except requests.exceptions.RequestException as e:
            bt.logging.error(f"Gateway API request error: {e}")
            raise

    def lookup_nodes(self, hotkeys: List[str]) -> Dict[str, List[Node]]:
        """
        Lookup nodes for given hotkeys.

        Args:
            hotkeys: List of hotkey addresses (max 100)

        Returns:
            Dict mapping hotkey to list of Node objects

        Raises:
            GatewayAPIError: If the API returns an error
            ValueError: If more than 100 hotkeys provided
        """
        if len(hotkeys) > 100:
            raise ValueError("Maximum 100 hotkeys allowed per request")

        if not hotkeys:
            return {}

        hotkeys_str = ",".join(hotkeys)
        endpoint = f"/public/validators/nodes/lookup/{self.api_key}"

        response = self._request("GET", endpoint, params={"hotkeys": hotkeys_str})

        # Parse response into Node objects
        result: Dict[str, List[Node]] = {}
        for hotkey, nodes_data in response.items():
            result[hotkey] = [
                Node(id=node["id"], region=node["region"])
                for node in nodes_data
            ]

        return result

    def get_statistics(self) -> StatisticsResponse:
        """
        Get node verification statistics.

        Returns:
            StatisticsResponse with node statistics and metadata

        Raises:
            GatewayAPIError: If the API returns an error
        """
        endpoint = f"/public/node-verifier/validators/statistics/{self.api_key}"
        response = self._request("GET", endpoint)

        # Parse statistics
        statistics = []
        for stat in response.get("statistics", []):
            statistics.append(NodeStatistics(
                node_id=stat["node_id"],
                health=CheckStats(
                    total=stat["health"]["total"],
                    passed=stat["health"]["passed"],
                ),
                data=CheckStats(
                    total=stat["data"]["total"],
                    passed=stat["data"]["passed"],
                ),
                benchmark=CheckStats(
                    total=stat["benchmark"]["total"],
                    passed=stat["benchmark"]["passed"],
                ),
            ))

        # Parse meta
        meta_data = response.get("meta", {})
        regions = {}
        for region_name, region_data in meta_data.get("regions", {}).items():
            regions[region_name] = RegionStats(
                success=region_data["success"],
                count=region_data["count"],
                latency=region_data["latency"],
                error=region_data.get("error"),
            )

        meta = StatisticsMeta(
            total_nodes=meta_data.get("total_nodes", 0),
            regions=regions,
            total_latency_ms=meta_data.get("total_latency_ms", 0),
        )

        return StatisticsResponse(statistics=statistics, meta=meta)

    def _rpc_request(
        self,
        endpoint: str,
        method: str,
        params: Optional[List[Any]] = None,
        request_id: int = 1,
        query_params: Optional[Dict[str, str]] = None,
    ) -> RPCResponse:
        """Internal method to make RPC requests."""
        body = {
            "id": request_id,
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
        }

        response = self._request("POST", endpoint, data=body, params=query_params)

        rpc_error = None
        if "error" in response:
            error_data = response["error"]
            rpc_error = RPCError(
                code=error_data.get("code", 0),
                message=error_data.get("message", ""),
            )

        return RPCResponse(
            jsonrpc=response.get("jsonrpc", "2.0"),
            id=response.get("id", request_id),
            result=response.get("result"),
            error=rpc_error,
            latency_ms=response.get("latency_ms"),
        )

    def rpc_call(
        self,
        method: str,
        node_id: str,
        region: str,
        params: Optional[List[Any]] = None,
        request_id: int = 1,
    ) -> RPCResponse:
        """
        Make a JSON-RPC call to a specific node through the validator endpoint.

        Args:
            method: The RPC method to call
            node_id: The node ID to route the request to
            region: The region (us, eu, as)
            params: Optional list of parameters for the RPC call
            request_id: The JSON-RPC request ID

        Returns:
            RPCResponse with the result and latency_ms (check is_error() for RPC errors)

        Raises:
            ValueError: If region is invalid
        """
        valid_regions = ["us", "eu", "as"]
        if region not in valid_regions:
            raise ValueError(f"Invalid region: {region}. Must be one of {valid_regions}")

        endpoint = f"/public/validators/rpc/bittensor/{self.api_key}"
        query_params = {"node_id": node_id, "region": region}

        return self._rpc_request(endpoint, method, params, request_id, query_params)

    def public_rpc_call(
        self,
        method: str,
        params: Optional[List[Any]] = None,
        request_id: int = 1,
    ) -> RPCResponse:
        """
        Make a JSON-RPC call through the public RPC endpoint (no authentication).

        Args:
            method: The RPC method to call
            params: Optional list of parameters for the RPC call
            request_id: The JSON-RPC request ID

        Returns:
            RPCResponse with the result (check is_error() for RPC errors)
        """
        endpoint = "/public/rpc/bittensor"
        return self._rpc_request(endpoint, method, params, request_id)
