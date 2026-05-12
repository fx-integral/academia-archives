"""Bittensor convenience wrappers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

try:
    import bittensor as bt
except ImportError:  # pragma: no cover - surfaced at call time
    bt = None


def get_subtensor(network: str) -> bt.Subtensor:
    if bt is None:  # pragma: no cover - safeguarded for tests
        raise RuntimeError("bittensor is not installed")
    return bt.subtensor(network=network)


def get_wallet(name: str, hotkey: str) -> bt.wallet:
    if bt is None:  # pragma: no cover
        raise RuntimeError("bittensor is not installed")
    return bt.wallet(name=name, hotkey=hotkey)


@dataclass(frozen=True)
class RegistrationResult:
    status: str
    success: bool
    uid: int | None
    hotkey: str
    extrinsic: str | None = None  # Extrinsic hash (e.g., "5759123-5")
    balance_before: float | None = None  # Balance before registration
    balance_after: float | None = None  # Balance after registration


def register_hotkey(
    *,
    network: str,
    wallet_name: str,
    hotkey_name: str,
    netuid: int,
    burned: bool = True,
    cuda: bool = False,
    wait_for_finalization: bool = True,
    wait_for_inclusion: bool = False,
    dev_id: int | list[int] | None = 0,
    tpb: int = 256,
    num_processes: int | None = None,
) -> RegistrationResult:
    """Register a hotkey on the target subnet and return the resulting UID."""

    subtensor = get_subtensor(network)
    try:
        wallet = get_wallet(wallet_name, hotkey_name)
        hotkey_ss58 = wallet.hotkey.ss58_address

        if subtensor.is_hotkey_registered(hotkey_ss58, netuid=netuid):
            neuron = subtensor.get_neuron_for_pubkey_and_subnet(hotkey_ss58, netuid)
            uid = None if getattr(neuron, "is_null", False) else getattr(neuron, "uid", None)
            return RegistrationResult(status="already", success=True, uid=uid, hotkey=hotkey_ss58)

        # Get balance before registration
        balance_before = None
        balance_after = None
        extrinsic = None

        try:
            balance_obj = subtensor.get_balance(wallet.coldkeypub.ss58_address)
            # Convert Balance object to float using .tao property
            balance_before = balance_obj.tao if hasattr(balance_obj, "tao") else float(balance_obj)
        except Exception:
            pass  # Balance may not be available, continue anyway

        if burned:
            # burned_register returns (success, block_info) or just success
            registration_result = subtensor.burned_register(
                wallet=wallet,
                netuid=netuid,
                wait_for_finalization=wait_for_finalization,
            )

            # Handle both return types: bool or (bool, message)
            if isinstance(registration_result, tuple):
                ok, message = registration_result
                if isinstance(message, str) and message:
                    extrinsic = message
            else:
                ok = registration_result

            status = "burned"
        else:
            ok = subtensor.register(
                wallet=wallet,
                netuid=netuid,
                wait_for_finalization=wait_for_finalization,
                wait_for_inclusion=wait_for_inclusion,
                cuda=cuda,
                dev_id=dev_id,
                tpb=tpb,
                num_processes=num_processes,
                log_verbose=False,
            )
            status = "pow"
            if isinstance(ok, tuple) and len(ok) == 2:
                ok, message = ok
                if isinstance(message, str):
                    extrinsic = message

        if not ok:
            return RegistrationResult(
                status=status,
                success=False,
                uid=None,
                hotkey=hotkey_ss58,
                balance_before=balance_before,
                balance_after=balance_after,
                extrinsic=extrinsic,
            )

        # Get balance after registration
        try:
            balance_obj = subtensor.get_balance(wallet.coldkeypub.ss58_address)
            # Convert Balance object to float using .tao property
            balance_after = balance_obj.tao if hasattr(balance_obj, "tao") else float(balance_obj)
        except Exception:
            pass

        neuron = subtensor.get_neuron_for_pubkey_and_subnet(hotkey_ss58, netuid)
        uid = None if getattr(neuron, "is_null", False) else getattr(neuron, "uid", None)

        return RegistrationResult(
            status=status,
            success=True,
            uid=uid,
            hotkey=hotkey_ss58,
            balance_before=balance_before,
            balance_after=balance_after,
            extrinsic=extrinsic,
        )
    finally:
        # Clean up subtensor connection
        try:
            if hasattr(subtensor, "close"):
                subtensor.close()
        except Exception:
            pass  # Silently ignore cleanup errors


def get_burn_cost(network: str, netuid: int) -> float | None:
    """Get the burn cost (registration cost) for a subnet.

    Args:
        network: Bittensor network name (e.g., "test", "finney")
        netuid: Subnet netuid

    Returns:
        Burn cost in TAO as a float, or None if unavailable
    """
    # Try async SubtensorInterface method (most reliable)
    try:
        from bittensor_cli.src.bittensor.balances import Balance  # type: ignore[import-not-found]
        from bittensor_cli.src.bittensor.subtensor_interface import (  # type: ignore[import-not-found]
            SubtensorInterface,
        )

        async def _fetch_burn_cost() -> float:
            async with SubtensorInterface(network=network) as subtensor_async:
                block_hash = await subtensor_async.substrate.get_chain_head()
                burn_raw = await subtensor_async.get_hyperparameter(
                    param_name="Burn",
                    netuid=netuid,
                    block_hash=block_hash,
                )
                register_cost = (
                    Balance.from_rao(int(burn_raw)) if burn_raw is not None else Balance(0)
                )
                tao_value = (
                    register_cost.tao if hasattr(register_cost, "tao") else float(register_cost)
                )
                return float(tao_value)

        return asyncio.run(_fetch_burn_cost())
    except ImportError:
        # bittensor-cli not available, try fallback synchronous method
        try:
            subtensor = get_subtensor(network)
            # Use get_hyperparameter("Burn", netuid) - this works synchronously
            if hasattr(subtensor, "get_hyperparameter"):
                burn_raw = subtensor.get_hyperparameter("Burn", netuid=netuid)
                if burn_raw is not None:
                    # Convert from rao to TAO
                    from bittensor import Balance

                    balance_obj = Balance.from_rao(int(burn_raw))
                    return balance_obj.tao if hasattr(balance_obj, "tao") else float(balance_obj)
        except Exception:
            pass
    except Exception as exc:
        # Log other exceptions but don't show warnings in normal operation
        import warnings

        warnings.warn(f"Failed to fetch burn cost: {exc}", UserWarning, stacklevel=2)

    return None


__all__ = [
    "get_subtensor",
    "get_wallet",
    "register_hotkey",
    "get_burn_cost",
    "RegistrationResult",
]
