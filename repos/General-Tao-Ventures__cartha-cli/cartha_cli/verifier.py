"""HTTP helpers for interacting with the Cartha verifier service."""

from __future__ import annotations

import time
from typing import Any

import requests  # type: ignore[import-untyped]

from .config import settings


class VerifierError(RuntimeError):
    """Raised when the verifier cannot be reached or returns an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _build_url(path: str) -> str:
    base = settings.verifier_url.rstrip("/")
    return f"{base}{path}"


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retry: bool = True,
) -> dict[str, Any]:
    """Make HTTP request with automatic retry logic.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path
        params: Query parameters
        json_data: JSON body for POST requests
        headers: Additional headers
        retry: Whether to retry on transient failures (default: True)
        
    Returns:
        Response JSON data as dict
        
    Raises:
        VerifierError: If request fails after retries
    """
    request_headers: dict[str, str] = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    url = _build_url(path)

    max_attempts = settings.retry_max_attempts if retry else 1
    backoff_factor = settings.retry_backoff_factor
    retry_statuses = settings.retry_on_status

    last_exception: Exception | None = None
    response: requests.Response | None = None
    
    for attempt in range(max_attempts):
        try:
            # Use separate connection and read timeouts
            # Connection timeout: 5s (fast fail if can't connect)
            # Read timeout: 60s (allow time for response to arrive after connection established)
            # This helps when verifier processes quickly but response transmission is slow
            response = requests.request(
                method,
                url,
                params=params,
                json=json_data,
                headers=request_headers,
                timeout=(5, 60),  # (connect_timeout, read_timeout) in seconds
            )
            
            # Check if we should retry based on status code
            if retry and attempt < max_attempts - 1 and response.status_code in retry_statuses:
                wait_time = backoff_factor ** attempt
                time.sleep(wait_time)
                continue  # Retry the request
            
            # If we get here, either success or non-retryable error - break and process
            break
            
        except requests.Timeout as exc:
            last_exception = exc
            # Retry timeouts if we have attempts left
            if retry and attempt < max_attempts - 1:
                wait_time = backoff_factor ** attempt
                time.sleep(wait_time)
                continue
            
            # Explicitly handle timeout - request took longer than allowed
            # This could be connection timeout (5s) or read timeout (60s)
            error_msg = (
                f"Request to verifier timed out after {max_attempts} attempt(s): {url}\n"
                "This is a CLI-side timeout.\n"
                "If verifier logs show request completed, this is likely slow network response transmission.\n"
                "Possible causes: network latency, large response size, or slow connection.\n"
                "Tip: Try again in a moment or check verifier logs to confirm request was processed."
            )
            raise VerifierError(error_msg) from exc
        except requests.RequestException as exc:  # pragma: no cover - network failure
            last_exception = exc
            # Retry network errors if we have attempts left
            if retry and attempt < max_attempts - 1:
                wait_time = backoff_factor ** attempt
                time.sleep(wait_time)
                continue
            
            # Provide more context about the failed URL
            error_msg = f"Failed to reach verifier at {url} after {max_attempts} attempt(s): {exc}"
            raise VerifierError(error_msg) from exc
    
    # If we exhausted retries without getting a response, raise the last exception
    if response is None and last_exception:
        raise VerifierError(f"Request failed after {max_attempts} attempts: {last_exception}") from last_exception
    
    # Process the response (response should be set at this point)
    assert response is not None  # nosec - response should be set if we got here

    try:
        data = response.json()
    except ValueError:
        data = None

    if response.status_code >= 400:
        if isinstance(data, dict):
            detail = data.get("detail") or data.get("error") or response.text
        else:
            detail = response.text or "Unknown verifier error"

        # Handle FastAPI validation errors which return detail as a list
        if isinstance(detail, list):
            # Format list of validation errors into a readable string
            formatted_errors = []
            for item in detail:
                if isinstance(item, dict):
                    # Extract field location and message
                    loc = item.get("loc", [])
                    msg = item.get("msg", "Validation error")
                    field = " -> ".join(str(x) for x in loc) if loc else "unknown"
                    formatted_errors.append(f"{field}: {msg}")
                else:
                    formatted_errors.append(str(item))
            detail = "; ".join(formatted_errors)
        elif isinstance(detail, str):
            detail = detail.strip()
        else:
            detail = str(detail)

        # Log error details for debugging (only in debug mode or for 500 errors)
        if response.status_code >= 500:
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Verifier error - URL: {url}")
            logger.debug(f"Verifier error - Status: {response.status_code}")
            logger.debug(f"Verifier error - Response: {response.text[:500]}")

        raise VerifierError(detail, status_code=response.status_code)

    if not isinstance(data, dict):
        raise VerifierError("Unexpected verifier response payload.")
    return data


def fetch_miner_status(
    *,
    hotkey: str,
    slot: str,
) -> dict[str, Any]:
    """Return miner status without authentication (public endpoint)."""
    return _request(
        "GET",
        "/v1/miner/status",
        params={"hotkey": hotkey, "slot": slot},
    )


def fetch_pair_status(
    *,
    hotkey: str,
    slot: str,
    network: str,
    netuid: int,
    message: str,
    signature: str,
) -> dict[str, Any]:
    """Return the status for a (hotkey, slotUID) pair after verifying ownership."""
    payload = {
        "hotkey": hotkey,
        "slot": slot,
        "network": network,
        "netuid": netuid,
        "message": message,
        "signature": signature,
    }
    return _request(
        "POST",
        "/v1/pair/status",
        json_data=payload,
    )


# REMOVED: fetch_pair_password and register_pair_password
# These functions are no longer needed - the new lock flow uses session tokens instead of passwords.
# The verifier endpoints /v1/pair/password/* have been removed.


def check_registration(
    *,
    hotkey: str,
    miner_slot: str | None = None,
    uid: str | None = None,
) -> dict[str, Any]:
    """Check if a hotkey is registered on subnet 35.
    
    Returns: {registered: bool, uid: int | None}
    """
    params: dict[str, Any] = {"hotkey": hotkey}
    if miner_slot is not None:
        params["minerSlot"] = miner_slot
    if uid is not None:
        params["uid"] = uid
    return _request(
        "GET",
        "/subnet/check-registration",
        params=params,
    )


def verify_hotkey(
    *,
    hotkey: str,
    signature: str,
    message: str,
) -> dict[str, Any]:
    """Verify Bittensor hotkey signature and get session token.
    
    Returns: {verified: bool, session_token: str, expires_at: int}
    """
    payload = {
        "hotkey": hotkey,
        "signature": signature,
        "message": message,
    }
    return _request(
        "POST",
        "/auth/verify-hotkey",
        json_data=payload,
    )


def request_lock_signature(
    *,
    session_token: str,
    pool_id: str,
    amount: int,
    lock_days: int,
    hotkey: str,
    miner_slot: str | None,
    uid: str | None,
    owner: str,
    chain_id: int,
    vault_address: str,
) -> dict[str, Any]:
    """Request EIP-712 LockRequest signature from verifier.
    
    Returns: {signature, timestamp, nonce, expiresAt, approveTx, lockTx}
    """
    payload = {
        "poolId": pool_id,
        "amount": amount,
        "lockDays": lock_days,
        "hotkey": hotkey,
        "owner": owner,
        "chainId": chain_id,
        "vaultAddress": vault_address,
    }
    if miner_slot is not None:
        payload["minerSlot"] = miner_slot
    if uid is not None:
        payload["uid"] = uid
    
    headers = {"Authorization": f"Bearer {session_token}"}
    return _request(
        "POST",
        "/lock/request-signature",
        json_data=payload,
        headers=headers,
    )


def get_lock_status(
    *,
    tx_hash: str,
) -> dict[str, Any]:
    """Check status of a lock transaction.
    
    Returns: {verified: bool, lockId: str | None, addedToEpoch: str | None, message: str | None}
    """
    return _request(
        "GET",
        "/lock/status",
        params={"tx_hash": tx_hash},  # Match endpoint parameter name (snake_case)
    )


def process_lock_transaction(
    *,
    tx_hash: str,
) -> dict[str, Any]:
    """Trigger immediate processing of a lock transaction.
    
    Returns: {success: bool, action: str, hotkey: str, slot: str, ...}
    """
    return _request(
        "POST",
        "/lock/process",
        json_data={"tx_hash": tx_hash},
    )


def fetch_pools() -> list[dict[str, Any]]:
    """Fetch available pools from verifier.
    
    Returns list of pools with:
    - name: Human-readable pool name (e.g., "BTC/USD")
    - pool_id: Hex pool ID (bytes32)
    - vault_address: Vault contract address
    - chain_id: Chain ID
    - network: Network name ("mainnet" or "testnet")
    """
    data = _request("GET", "/pools")
    return data.get("pools", [])


# REMOVED: Old endpoints - replaced by new lock flow
# fetch_pair_password, register_pair_password, submit_lock_proof removed


__all__ = [
    "VerifierError",
    "_build_url",
    "_request",
    "fetch_pair_status",
    "fetch_miner_status",
    "check_registration",
    "verify_hotkey",
    "request_lock_signature",
    "get_lock_status",
    "process_lock_transaction",
    "fetch_pools",
]
