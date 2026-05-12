import os
import asyncio
import threading
import bittensor as bt
import utils.logger as logger
from typing import Optional, Any


class SubtensorWrapper:
    """
    Wrapper for bittensor async_subtensor with automatic reconnection on failure.
    """

    def __init__(self, endpoint: Optional[str] = None, fallback: Optional[str] = None):
        self._network = os.getenv("SUBTENSOR_NETWORK")  # e.g., "finney"
        self._endpoint = endpoint or os.getenv("SUBTENSOR_ADDRESS")  # Custom URL if set
        self._fallback = fallback or "wss://test.finney.opentensor.ai:443"
        self._subtensor: Optional[bt.AsyncSubtensor] = None
        self._lock = asyncio.Lock()

    async def _create_connection(self) -> bt.AsyncSubtensor:
        """Create and initialize a new subtensor connection."""
        try:
            logger.info(f"Attempting to connect with network: {self._network}, endpoint: {self._endpoint}")

            # If _endpoint is a custom URL, use it as primary via fallback_endpoints
            if self._endpoint and self._endpoint.startswith("ws"):
                subtensor = bt.AsyncSubtensor(
                    network=self._network,  # Still use "finney" for fallbacks
                    fallback_endpoints=[self._endpoint],  # Prioritize custom URL
                )
            else:
                # Use network directly (for cases where SUBTENSOR_ADDRESS is not a URL)
                subtensor = bt.AsyncSubtensor(network=self._endpoint or self._network)

            await subtensor.initialize()
            logger.info(f"Successfully connected to subtensor")
            return subtensor
        except Exception as e:
            logger.warning(f"Failed to connect to primary: {e}")
            if self._fallback:
                logger.info(f"Attempting fallback: {self._fallback}")
                try:
                    subtensor = bt.AsyncSubtensor(
                        network=self._network, fallback_endpoints=[self._fallback]
                    )
                    await subtensor.initialize()
                    logger.info(f"Successfully connected to fallback")
                    return subtensor
                except Exception as fallback_error:
                    logger.error(f"Failed to connect to fallback: {fallback_error}")
                    raise
            raise

    async def ensure_connected(self):
        """Ensure we have a valid connection."""
        async with self._lock:
            if self._subtensor is None:
                logger.info("Connecting subtensor...")
                self._subtensor = await self._create_connection()
            else:
                logger.debug("Reusing existing subtensor connection")
            return self._subtensor

    def __getattr__(self, name: str) -> Any:
        """
        Proxy all attribute access to the underlying subtensor.
        Automatically reconnects on failure.
        """

        async def wrapper(*args, **kwargs):
            try:
                subtensor = await self.ensure_connected()
                attr = getattr(subtensor, name)

                if not callable(attr):
                    return attr

                result = attr(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                else:
                    return result
            except Exception as e:  # Changed from BaseException
                logger.debug(f"Method {name} failed, attempting reconnection: {e}")

                async with self._lock:
                    if self._subtensor:
                        try:
                            await self._subtensor.close()
                        except Exception:
                            pass
                        self._subtensor = None

                    self._subtensor = await self._create_connection()

                # Retry after reconnection
                attr = getattr(self._subtensor, name)

                if not callable(attr):
                    return attr

                result = attr(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                else:
                    return result

        return wrapper

    @property
    def substrate(self):
        return self._subtensor.substrate if self._subtensor else None

    async def close(self):
        """Close the connection."""
        async with self._lock:
            if self._subtensor:
                try:
                    await self._subtensor.close()
                except Exception as e:
                    logger.debug(f"Error closing subtensor: {e}")
                finally:
                    self._subtensor = None


# Global instance
_GLOBAL_SUBTENSOR: Optional[SubtensorWrapper] = None
_GLOBAL_LOCK = threading.Lock()


def get_global_subtensor() -> SubtensorWrapper:
    """
    Get or create the global SubtensorWrapper instance.

    Returns:
        SubtensorWrapper: The global subtensor wrapper instance.
    """
    global _GLOBAL_SUBTENSOR

    with _GLOBAL_LOCK:
        if _GLOBAL_SUBTENSOR is None:
            _GLOBAL_SUBTENSOR = SubtensorWrapper()
        return _GLOBAL_SUBTENSOR


async def get_subtensor() -> SubtensorWrapper:
    """
    Get the global SubtensorWrapper instance (async version).
    Ensures the connection is established before returning.

    Returns:
        SubtensorWrapper: The connected subtensor wrapper.
    """
    wrapper = get_global_subtensor()
    await wrapper.ensure_connected()
    return wrapper


async def close_subtensor():
    """Close the global subtensor connection."""
    global _GLOBAL_SUBTENSOR
    if _GLOBAL_SUBTENSOR:
        await _GLOBAL_SUBTENSOR.close()
        _GLOBAL_SUBTENSOR = None
