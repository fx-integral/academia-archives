"""
BeamCore API client for validator-side v2 routes.
"""

import logging
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


def build_signed_auth_headers(
    wallet,
    hotkey: str,
    action: str = "request",
) -> Dict[str, str]:
    """Build signed authentication headers for validator requests."""
    timestamp = int(time.time())
    nonce = secrets.token_hex(16)
    message = f"validator_auth:{hotkey}:{timestamp}:{action}:{nonce}"
    signature = wallet.hotkey.sign(message.encode("utf-8"))
    return {
        "X-Validator-Hotkey": hotkey,
        "X-Validator-Signature": signature.hex(),
        "X-Validator-Timestamp": str(timestamp),
        "X-Validator-Nonce": nonce,
        "X-Validator-Action": action,
    }


@dataclass
class UIDRanges:
    subnet_orchestrator_uid: int
    public_orchestrator_uid_start: int
    public_orchestrator_uid_end: int
    reserved_orchestrator_uid_start: int
    reserved_orchestrator_uid_end: int
    max_orchestrators: int

    def is_valid_public_uid(self, uid: int) -> bool:
        return self.public_orchestrator_uid_start <= uid <= self.public_orchestrator_uid_end

    def is_valid_reserved_uid(self, uid: int) -> bool:
        return self.reserved_orchestrator_uid_start <= uid <= self.reserved_orchestrator_uid_end

    def is_subnet_orchestrator_uid(self, uid: int) -> bool:
        return uid == self.subnet_orchestrator_uid

    def is_valid_orchestrator_uid(self, uid: int) -> bool:
        return (
            self.is_subnet_orchestrator_uid(uid)
            or self.is_valid_public_uid(uid)
            or self.is_valid_reserved_uid(uid)
        )


@dataclass
class ScoreSubmission:
    epoch: int
    orchestrator_hotkey: str
    orchestrator_uid: int
    bandwidth_score: float = 0.0
    compliance_score: float = 1.0
    final_score: float = 0.0
    total_proofs_published: int = 0
    total_bytes_claimed: int = 0
    total_workers_active: int = 0
    avg_bandwidth_mbps: float = 0.0
    proofs_verified: int = 0
    proofs_rejected: int = 0
    proofs_challenged: int = 0
    verification_rate: float = 0.0
    spot_checks_attempted: int = 0
    spot_checks_passed: int = 0
    spot_check_rate: float = 0.0


@dataclass
class SpotCheckSubmission:
    epoch: int
    orchestrator_hotkey: str
    proof_task_id: str
    worker_id: str
    worker_hotkey: str
    claimed_bytes: int
    claimed_bandwidth_mbps: float
    response_valid: bool
    verification_passed: bool
    orchestrator_uid: Optional[int] = None
    challenge_chunk_hash: Optional[str] = None
    challenge_offset: Optional[int] = None
    verification_notes: Optional[str] = None


class SubnetCoreClient:
    """Client for communicating with BeamCore validator routes."""

    def __init__(
        self,
        base_url: str,
        validator_hotkey: str,
        wallet=None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.validator_hotkey = validator_hotkey
        self.wallet = wallet
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _get_auth_headers(self, action: str = "request") -> Dict[str, str]:
        if self.wallet:
            try:
                return build_signed_auth_headers(self.wallet, self.validator_hotkey, action)
            except Exception as exc:
                logger.warning("Failed to build signed auth headers for %s: %s", action, exc)
        return {"X-Validator-Hotkey": self.validator_hotkey}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        action: str = "request",
        timeout: Optional[float] = None,
        **kwargs,
    ) -> httpx.Response:
        client = await self._get_client()
        headers = self._get_auth_headers(action)
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        request_kwargs = kwargs.copy()
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        return await client.request(
            method, f"{self.base_url}{path}", headers=headers, **request_kwargs
        )

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def submit_scores(self, epoch: int, scores: List[ScoreSubmission]) -> Dict[str, Any]:
        payload = {
            "validator_hotkey": self.validator_hotkey,
            "epoch": epoch,
            "scores": [asdict(score) for score in scores],
        }
        response = await self._request(
            "POST",
            "/validators/scores",
            action="submit_scores",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def submit_spot_check(self, check: SpotCheckSubmission) -> Dict[str, Any]:
        response = await self._request(
            "POST",
            "/validators/spot-checks",
            action="submit_spot_check",
            json=asdict(check),
        )
        response.raise_for_status()
        return response.json()

    async def submit_weight_proof(
        self,
        epoch: int,
        block_number: int,
        uids: List[int],
        weights: List[float],
        on_chain_hash: str,
        formula_version: Optional[str] = None,
        params_hash: Optional[str] = None,
        total_stake: float = 0.0,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "validator_hotkey": self.validator_hotkey,
            "epoch": epoch,
            "block_number": block_number,
            "uids": uids,
            "weights": [round(weight, 6) for weight in weights],
            "total_stake": total_stake,
            "on_chain_hash": on_chain_hash,
        }
        if formula_version is not None:
            payload["formula_version"] = formula_version
        if params_hash is not None:
            payload["params_hash"] = params_hash

        response = await self._request(
            "POST",
            "/validators/weights",
            action="submit_weight_proof",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def get_unverified_proofs(
        self,
        epoch: Optional[int] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit}
        if epoch is not None:
            params["epoch"] = epoch
        response = await self._request(
            "GET",
            "/pob/unverified",
            action="get_unverified_proofs",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def verify_proof(
        self,
        proof_id: str,
        passed: bool,
        signature_valid: bool = False,
        timing_valid: bool = False,
        bandwidth_valid: bool = False,
        canary_valid: bool = False,
        geo_valid: bool = False,
        verification_notes: Optional[str] = None,
        measured_latency_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        notes: List[str] = [
            f"signature_valid={signature_valid}",
            f"timing_valid={timing_valid}",
            f"bandwidth_valid={bandwidth_valid}",
            f"canary_valid={canary_valid}",
            f"geo_valid={geo_valid}",
        ]
        if measured_latency_ms is not None:
            notes.append(f"measured_latency_ms={measured_latency_ms:.3f}")
        if verification_notes:
            notes.append(verification_notes)

        response = await self._request(
            "POST",
            f"/pob/{proof_id}/verify",
            action="verify_proof",
            json={
                "passed": passed,
                "validator_hotkey": self.validator_hotkey,
                "notes": "; ".join(notes),
            },
        )
        response.raise_for_status()
        return response.json()

    async def get_latest_data_epoch(self) -> Optional[int]:
        try:
            response = await self._request(
                "GET",
                "/pob/latest-epoch",
                action="get_latest_data_epoch",
            )
            response.raise_for_status()
            return response.json().get("epoch")
        except Exception as exc:
            logger.warning("Failed to get latest data epoch: %s", exc)
            return None

    async def get_proofs_from_subnetcore(
        self,
        epoch: Optional[int] = None,
        orchestrator_hotkey: Optional[str] = None,
        worker_id: Optional[str] = None,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit}
        if epoch is not None:
            params["epoch"] = epoch
        if orchestrator_hotkey:
            params["orchestrator_hotkey"] = orchestrator_hotkey
        if worker_id:
            params["worker_id"] = worker_id
        if status:
            params["status"] = status
        response = await self._request(
            "GET",
            "/pob",
            action="get_proofs",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def get_orchestrators(
        self,
        active_only: bool = True,
        limit: int = 256,
    ) -> Dict[str, Any]:
        response = await self._request(
            "GET",
            "/validators/orchestrators",
            action="get_orchestrators",
            params={"active_only": active_only, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    async def get_recommended_weights(self, epoch: int) -> Dict[str, Any]:
        response = await self._request(
            "GET",
            f"/validators/weights/{epoch}",
            action="get_recommended_weights",
        )
        response.raise_for_status()
        return response.json()

    async def get_uid_ranges(self) -> Optional[UIDRanges]:
        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/config/uid-ranges")
            response.raise_for_status()
            data = response.json()
            return UIDRanges(
                subnet_orchestrator_uid=data["subnet_orchestrator_uid"],
                public_orchestrator_uid_start=data["public_orchestrator_uid_start"],
                public_orchestrator_uid_end=data["public_orchestrator_uid_end"],
                reserved_orchestrator_uid_start=data["reserved_orchestrator_uid_start"],
                reserved_orchestrator_uid_end=data["reserved_orchestrator_uid_end"],
                max_orchestrators=data["max_orchestrators"],
            )
        except Exception as exc:
            logger.error("Error fetching UID ranges: %s", exc)
            return None

    async def get_network_config(self) -> Optional[dict]:
        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/config/network")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("Error fetching network config: %s", exc)
            return None

    async def submit_heartbeat(
        self,
        validator_uid: int,
        status: str = "online",
        last_epoch_scored: Optional[int] = None,
        health_info: Optional[dict] = None,
        external_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        response = await self._request(
            "POST",
            "/validators/heartbeat",
            action="heartbeat",
            json={
                "validator_hotkey": self.validator_hotkey,
                "validator_uid": validator_uid,
                "status": status,
                "timestamp": int(time.time() * 1e6),
                "last_epoch_scored": last_epoch_scored,
                "health_info": health_info,
                "external_url": external_url,
            },
        )
        response.raise_for_status()
        return response.json()


_client: Optional[SubnetCoreClient] = None


def get_subnet_core_client() -> Optional[SubnetCoreClient]:
    return _client


def init_subnet_core_client(
    base_url: str,
    validator_hotkey: str,
    wallet=None,
    timeout: float = 30.0,
) -> SubnetCoreClient:
    global _client
    _client = SubnetCoreClient(base_url, validator_hotkey, wallet, timeout)
    return _client


async def close_subnet_core_client():
    global _client
    if _client:
        await _client.close()
        _client = None
