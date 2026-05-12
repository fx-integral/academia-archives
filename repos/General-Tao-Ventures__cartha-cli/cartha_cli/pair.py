"""Pair authentication and status utilities for the Cartha CLI."""

from __future__ import annotations

import time
from typing import Any

import bittensor as bt
import typer
from rich.console import Console

from .bt import get_subtensor
from .utils import format_timestamp
from .verifier import VerifierError, fetch_pair_status
from .wallet import CHALLENGE_PREFIX, CHALLENGE_TTL_SECONDS, load_wallet

console = Console()


def get_uid_from_hotkey(
    *,
    network: str,
    netuid: int,
    hotkey: str,
) -> int | None:
    """Get the UID for a hotkey on the subnet.

    Args:
        network: Bittensor network name
        netuid: Subnet netuid
        hotkey: Hotkey SS58 address

    Returns:
        UID if registered, None if not registered or deregistered
    """
    subtensor = None

    try:
        subtensor = get_subtensor(network)

        # Try to get UID directly - if successful, they're registered
        try:
            uid = subtensor.get_uid_for_hotkey_on_subnet(
                hotkey_ss58=hotkey, netuid=netuid
            )
            if uid is not None and uid >= 0:
                return int(uid)
        except AttributeError:
            # Method doesn't exist in this bittensor version
            return None
        except Exception:
            # Any other error means not registered or network issue
            return None

        return None
    except Exception as exc:
        error_msg = str(exc)
        if "nodename" in error_msg.lower() or "servname" in error_msg.lower():
            console.print(
                f"[bold red]Network error[/]: Unable to connect to Bittensor {network} network: {error_msg}"
            )
            console.print(
                "[yellow]This might be a DNS/network connectivity issue. Please check your internet connection.[/]"
            )
            raise typer.Exit(code=1) from None
        # Re-raise other exceptions as-is
        raise
    finally:
        # Clean up connections
        try:
            if subtensor is not None:
                if hasattr(subtensor, "close"):
                    subtensor.close()
                del subtensor
        except Exception:
            pass


def ensure_pair_registered(
    *,
    network: str,
    netuid: int,
    slot: str,
    hotkey: str,
) -> None:
    """Ensure a pair is registered on the subnet.

    Args:
        network: Bittensor network name
        netuid: Subnet netuid
        slot: Slot UID
        hotkey: Hotkey SS58 address

    Raises:
        typer.Exit: If pair is not registered or UID mismatch
    """
    subtensor = None
    metagraph = None
    try:
        subtensor = get_subtensor(network)
        metagraph = subtensor.metagraph(netuid)
        slot_index = int(slot)
        if slot_index < 0 or slot_index >= len(metagraph.hotkeys):
            console.print(
                f"[bold red]UID {slot} not found[/] in the metagraph (netuid {netuid})."
            )
            raise typer.Exit(code=1)
        registered_hotkey = metagraph.hotkeys[slot_index]
        if registered_hotkey != hotkey:
            console.print(
                f"[bold red]UID mismatch[/]: slot {slot} belongs to a different hotkey, not {hotkey}. Please verify your inputs."
            )
            raise typer.Exit(code=1)
    except Exception as exc:
        error_msg = str(exc)
        if "nodename" in error_msg.lower() or "servname" in error_msg.lower():
            console.print(
                f"[bold red]Network error[/]: Unable to connect to Bittensor {network} network: {error_msg}"
            )
            console.print(
                "[yellow]This might be a DNS/network connectivity issue. Please check your internet connection.[/]"
            )
            raise typer.Exit(code=1) from None
        # Re-raise other exceptions as-is
        raise
    finally:
        # Clean up connections
        try:
            if subtensor is not None:
                if hasattr(subtensor, "close"):
                    subtensor.close()
                del subtensor
            if metagraph is not None:
                del metagraph
        except Exception:
            pass


def build_pair_auth_payload(
    *,
    network: str,
    netuid: int,
    slot: str,
    hotkey: str,
    wallet_name: str,
    wallet_hotkey: str,
    skip_metagraph_check: bool = False,
    challenge_prefix: str | None = None,
) -> dict[str, Any]:
    """Build authentication payload for pair status/password requests or lock flow.

    Args:
        network: Bittensor network name
        netuid: Subnet netuid
        slot: Slot UID
        hotkey: Hotkey SS58 address
        wallet_name: Coldkey wallet name
        wallet_hotkey: Hotkey name
        skip_metagraph_check: Skip metagraph validation check
        challenge_prefix: Challenge prefix (defaults to CHALLENGE_PREFIX, use "cartha-lock" for lock flow)

    Returns:
        Dictionary with message, signature, and expires_at
    """
    wallet = load_wallet(wallet_name, wallet_hotkey, hotkey)
    if not skip_metagraph_check:
        ensure_pair_registered(
            network=network, netuid=netuid, slot=slot, hotkey=hotkey
        )

    timestamp = int(time.time())
    prefix = challenge_prefix or CHALLENGE_PREFIX
    message = (
        f"{prefix}|network:{network}|netuid:{netuid}|slot:{slot}|"
        f"hotkey:{hotkey}|ts:{timestamp}"
    )
    message_bytes = message.encode("utf-8")
    signature_bytes = wallet.hotkey.sign(message_bytes)

    verifier_keypair = bt.Keypair(ss58_address=hotkey)
    if not verifier_keypair.verify(message_bytes, signature_bytes):
        console.print("[bold red]Unable to verify the ownership signature locally.[/]")
        raise typer.Exit(code=1)

    expires_at = timestamp + CHALLENGE_TTL_SECONDS
    expiry_time = format_timestamp(expires_at)
    console.print(
        "[bold green]Ownership challenge signed[/] "
        f"(expires in {CHALLENGE_TTL_SECONDS}s at {expiry_time})."
    )

    return {
        "message": message,
        "signature": "0x" + signature_bytes.hex(),
        "expires_at": expires_at,
    }


# REMOVED: request_pair_status_or_password - replaced by new lock flow
# Old function removed as part of new lock flow implementation

