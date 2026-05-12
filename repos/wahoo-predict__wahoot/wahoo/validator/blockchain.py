import logging
from typing import List, Optional, Tuple, Any

from .api import SET_WEIGHTS_MAX_RETRIES

logger = logging.getLogger(__name__)

_last_successful_block: Optional[int] = None
_last_cooldown_log_block: Optional[int] = None


def set_weights_with_retry(
    subtensor: Any,
    wallet: Any,
    netuid: int,
    uids: List[int],
    weights: Any,
    *,
    max_retries: int = SET_WEIGHTS_MAX_RETRIES,
    commit_period: int = 32,  # Default Bittensor commit period in blocks
) -> Tuple[Optional[str], bool]:
    global _last_successful_block, _last_cooldown_log_block
    max_attempts = max_retries + 1
    attempt = 0

    # Get current block number
    current_block = None
    try:
        if hasattr(subtensor, "block"):
            current_block = subtensor.block
    except Exception:
        pass

    while attempt < max_attempts:
        attempt += 1

        if attempt > 1:
            logger.info(
                f"set_weights() retry attempt {attempt}/{max_attempts} "
                f"(max_retries={max_retries})"
            )

        try:
            # Convert weights to proper format (numpy array or list) if it's a torch tensor
            import torch
            import numpy as np
            
            if isinstance(weights, torch.Tensor):
                weights = weights.detach().cpu().numpy()
            elif not isinstance(weights, (list, np.ndarray)):
                weights = list(weights) if hasattr(weights, '__iter__') else [weights]
            
            # Ensure uids is a list
            if not isinstance(uids, list):
                uids = list(uids) if hasattr(uids, '__iter__') else [uids]
            
            # Log the parameters being passed for debugging
            logger.debug(
                f"Calling set_weights() with netuid={netuid}, "
                f"uids_count={len(uids)}, weights_count={len(weights)}, "
                f"weights_type={type(weights).__name__}"
            )
            
            result = subtensor.set_weights(
                wallet=wallet,
                netuid=netuid,
                uids=uids,
                weights=weights,
            )
            
            # Log the result type for debugging
            logger.debug(f"set_weights() returned type: {type(result)}")
            
            # Check for cooldown message in debug logs or response
            # Sometimes bittensor returns empty ExtrinsicResponse when "too soon"
            # but logs the actual message to debug
            import logging as std_logging
            bittensor_logger = std_logging.getLogger('bittensor')
            if hasattr(bittensor_logger, 'handlers'):
                # Check if there's a "too soon" message in recent logs
                # This is a workaround for bittensor 10.0.0 not populating error field
                pass

            # Handle ExtrinsicResponse objects (bittensor >= 10.0.0)
            if hasattr(result, 'success') and hasattr(result, 'message'):
                # This is an ExtrinsicResponse object
                if result.success:
                    # Extract transaction hash from extrinsic_receipt if available
                    transaction_hash = None
                    if hasattr(result, 'extrinsic_receipt') and result.extrinsic_receipt is not None:
                        # Try to get hash from extrinsic_receipt
                        if hasattr(result.extrinsic_receipt, 'hash'):
                            transaction_hash = result.extrinsic_receipt.hash
                        elif hasattr(result.extrinsic_receipt, 'tx_hash'):
                            transaction_hash = result.extrinsic_receipt.tx_hash
                        # If hash is in string representation, try to extract it
                        elif hasattr(result.extrinsic_receipt, '__str__'):
                            receipt_str = str(result.extrinsic_receipt)
                            # Extract hash from string like "ExtrinsicReceipt<hash:0x...>"
                            if 'hash:' in receipt_str:
                                try:
                                    hash_start = receipt_str.find('hash:') + 5
                                    hash_end = receipt_str.find('>', hash_start)
                                    if hash_end > hash_start:
                                        transaction_hash = receipt_str[hash_start:hash_end].strip()
                                except Exception:
                                    pass
                    
                    # Fallback to message or a default value
                    if not transaction_hash:
                        transaction_hash = result.message if result.message else "success"
                    
                    logger.info(
                        f"set_weights() succeeded on attempt {attempt}/{max_attempts}. "
                        f"Transaction hash: {transaction_hash}. "
                        f"UIDs: {len(uids)} miners"
                    )
                    try:
                        if hasattr(subtensor, "block"):
                            _last_successful_block = subtensor.block
                            _last_cooldown_log_block = None
                    except Exception:
                        pass
                    return transaction_hash, True
                else:
                    # Handle failure case - extract error message
                    message = None
                    if hasattr(result, 'error') and result.error is not None:
                        message = str(result.error)
                    elif hasattr(result, 'message') and result.message:
                        message = result.message
                    
                    # If still no message, check if it's likely a cooldown issue
                    # (bittensor 10.0.0 sometimes returns empty ExtrinsicResponse for "too soon")
                    if not message:
                        # Check if all fields are None - this often indicates "too soon" cooldown
                        all_none = (
                            result.extrinsic is None
                            and result.extrinsic_receipt is None
                            and result.error is None
                            and result.message is None
                        )
                        
                        if all_none:
                            # This is likely a cooldown period issue
                            # Bittensor 10.0.0 doesn't populate error field for "too soon"
                            message = "too soon to set weights (cooldown period)"
                            logger.debug(
                                "Detected likely cooldown period - empty ExtrinsicResponse "
                                "with all None fields (bittensor 10.0.0 issue)"
                            )
                        else:
                            # Try to get details from data attribute or string representation
                            if hasattr(result, 'data') and result.data:
                                message = f"Error data: {result.data}"
                            elif hasattr(result, 'extrinsic') and result.extrinsic:
                                message = f"Extrinsic error: {result.extrinsic}"
                            else:
                                # Log full response for debugging when message is unknown
                                try:
                                    result_str = str(result)
                                    if len(result_str) > 800:
                                        result_str = result_str[:800] + "..."
                                    message = f"Unknown error. Full response: {result_str}"
                                except Exception:
                                    message = "Unknown error - unable to extract response details"
                    
                    message_lower = message.lower()
                    
                    if (
                        "too soon" in message_lower
                        or "no attempt made" in message_lower
                    ):
                        next_commit_block = None
                        blocks_remaining = None
                        if (
                            current_block is not None
                            and _last_successful_block is not None
                        ):
                            next_commit_block = _last_successful_block + commit_period
                            blocks_remaining = max(0, next_commit_block - current_block)

                        should_log = False
                        if current_block is not None:
                            if (
                                _last_cooldown_log_block is None
                                or _last_cooldown_log_block != current_block
                            ):
                                should_log = True
                                _last_cooldown_log_block = current_block
                        else:
                            should_log = True

                        if should_log:
                            if blocks_remaining is not None and blocks_remaining > 0:
                                logger.debug(
                                    f"Weights on cooldown (next commit window in ~{blocks_remaining} blocks). "
                                    f"Current block: {current_block}, Last commit: {_last_successful_block}"
                                )
                            else:
                                logger.debug(
                                    "Weights on cooldown. This is normal - weights can only be committed periodically."
                                )

                        return None, True
                    else:
                        logger.warning(
                            f"set_weights() failed on attempt {attempt}/{max_attempts}: {message}"
                        )
                        if attempt >= max_attempts:
                            logger.error(
                                f"set_weights() exhausted all {max_attempts} attempts. "
                                f"Last error: {message}. "
                                f"Affected UIDs: {uids[:10]}..."
                            )
                            return None, False
                        continue

            if isinstance(result, tuple) and len(result) == 2:
                success, message = result
                if success:
                    transaction_hash = message if message else "success"
                    logger.info(
                        f"set_weights() succeeded on attempt {attempt}/{max_attempts}. "
                        f"Transaction hash: {transaction_hash}. "
                        f"UIDs: {len(uids)} miners"
                    )
                    try:
                        if hasattr(subtensor, "block"):
                            _last_successful_block = subtensor.block
                            _last_cooldown_log_block = None
                    except Exception:
                        pass
                    return transaction_hash, True
                else:
                    message_lower = message.lower() if message else ""
                    if (
                        "too soon" in message_lower
                        or "no attempt made" in message_lower
                    ):
                        next_commit_block = None
                        blocks_remaining = None
                        if (
                            current_block is not None
                            and _last_successful_block is not None
                        ):
                            next_commit_block = _last_successful_block + commit_period
                            blocks_remaining = max(0, next_commit_block - current_block)

                        should_log = False
                        if current_block is not None:
                            if (
                                _last_cooldown_log_block is None
                                or _last_cooldown_log_block != current_block
                            ):
                                should_log = True
                                _last_cooldown_log_block = current_block
                        else:
                            should_log = True

                        if should_log:
                            if blocks_remaining is not None and blocks_remaining > 0:
                                logger.debug(
                                    f"Weights on cooldown (next commit window in ~{blocks_remaining} blocks). "
                                    f"Current block: {current_block}, Last commit: {_last_successful_block}"
                                )
                            else:
                                logger.debug(
                                    "Weights on cooldown. This is normal - weights can only be committed periodically."
                                )

                        return None, True
                    else:
                        logger.warning(
                            f"set_weights() failed on attempt {attempt}/{max_attempts}: {message}"
                        )
                        if attempt >= max_attempts:
                            logger.error(
                                f"set_weights() exhausted all {max_attempts} attempts. "
                                f"Last error: {message}. "
                                f"Affected UIDs: {uids[:10]}..."
                            )
                            return None, False
                        continue

            transaction_hash: Optional[str] = None
            if isinstance(result, str):
                transaction_hash = result
            elif isinstance(result, dict) and "tx_hash" in result:
                transaction_hash = result["tx_hash"]
            elif isinstance(result, dict) and "hash" in result:
                transaction_hash = result["hash"]
            elif result is True or result is None:
                transaction_hash = "success"

            if transaction_hash:
                logger.info(
                    f"set_weights() succeeded on attempt {attempt}/{max_attempts}. "
                    f"Transaction hash: {transaction_hash}. "
                    f"UIDs: {len(uids)} miners"
                )
                try:
                    if hasattr(subtensor, "block"):
                        _last_successful_block = subtensor.block
                        _last_cooldown_log_block = None
                except Exception:
                    pass

                return transaction_hash, True
            else:
                logger.warning(
                    f"set_weights() returned unclear result on attempt {attempt}/{max_attempts}: {result}"
                )
                if attempt >= max_attempts:
                    logger.error(
                        f"set_weights() exhausted all {max_attempts} attempts. "
                        f"Affected UIDs: {uids[:10]}..."
                    )
                    return None, False
                continue

        except Exception as exc:
            failure_type = type(exc).__name__
            failure_reason = str(exc)
            
            # Log full traceback for debugging
            import traceback
            logger.debug(
                f"set_weights() exception traceback:\n{traceback.format_exc()}"
            )

            logger.warning(
                f"set_weights() failed on attempt {attempt}/{max_attempts}: "
                f"{failure_type}: {failure_reason}"
            )

            is_transient = _is_transient_error(exc)

            if attempt >= max_attempts or not is_transient:
                logger.error(
                    f"set_weights() failed after {attempt} attempt(s). "
                    f"Failure type: {failure_type}. "
                    f"Failure reason: {failure_reason}. "
                    f"Affected UIDs: {uids[:10]}..."
                )

                return None, False

            logger.info(
                f"Transient error detected, retrying set_weights() "
                f"(attempt {attempt}/{max_attempts})"
            )
            continue

    logger.error("set_weights() exhausted all retries")
    return None, False


def _is_transient_error(exc: Exception) -> bool:
    error_str = str(exc).lower()
    error_type = type(exc).__name__.lower()

    transient_keywords = [
        "timeout",
        "connection",
        "network",
        "rpc",
        "temporary",
        "unavailable",
        "503",
        "502",
        "504",
    ]

    non_transient_keywords = [
        "nonce",
        "insufficient",
        "balance",
        "invalid",
        "unauthorized",
        "forbidden",
        "400",
        "401",
        "403",
    ]

    for keyword in non_transient_keywords:
        if keyword in error_str or keyword in error_type:
            return False

    for keyword in transient_keywords:
        if keyword in error_str or keyword in error_type:
            return True

    return False


def get_last_successful_block() -> Optional[int]:
    return _last_successful_block


def reset_last_successful_block() -> None:
    global _last_successful_block, _last_cooldown_log_block
    _last_successful_block = None
    _last_cooldown_log_block = None
