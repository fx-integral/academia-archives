#!/usr/bin/env python3
"""
Simple per-iteration validator for **Subnet 66 – Oceans** (noise‑free logging).

- No epoch detection / waiting.
- Runs forward(); then sleeps a random 10–20 minutes before next iteration.
"""

# ── GLOBAL LOGGING PATCH (must be first!) ────────────────────────────────
import logging

_NOISY_LINE = "Adding PortableRegistry from metadata to type registry"


class _HidePortableRegistryNoise(logging.Filter):
    """Blocks only the single DEBUG line that scalecodec prints incessantly."""
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        return _NOISY_LINE not in record.getMessage()


# Single filter instance reused everywhere
_suppress_filter = _HidePortableRegistryNoise()

# 1️⃣  Attach to the *root* logger immediately
logging.getLogger().addFilter(_suppress_filter)

# 2️⃣  Make sure **all future handlers** get the filter automatically
_original_add_handler = logging.Logger.addHandler


def _patched_add_handler(self: logging.Logger, hdlr: logging.Handler):
    hdlr.addFilter(_suppress_filter)
    return _original_add_handler(self, hdlr)


logging.Logger.addHandler = _patched_add_handler

# 3️⃣  Attach directly to the known noisy loggers (and their descendants)
for _name in (
    "scalecodec",          # parent
    "scalecodec.base",     # real emitter
    "substrateinterface",  # for good measure
):
    logging.getLogger(_name).addFilter(_suppress_filter)
# ─────────────────────────────────────────────────────────────────────────

# ── standard imports (keep them **after** the patch above) ───────────────
import asyncio
import random
import time
import traceback

import bittensor as bt

from base.validator import BaseValidatorNeuron
from validator.vote_fetcher import VoteFetcher
from validator.liquidity_fetcher import LiquidityFetcher
from validator.rewards import RewardCalculator
from validator.forward import forward


class OceansValidator(BaseValidatorNeuron):
    """
    Minimal validator (no epoch logic):
      • Instantiates Oceans components (stateless).
      • In the run-loop: sync → forward() → sleep 10–20 min → repeat.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ––– Oceans components (no cache / persistence)
        self.vote_fetcher = VoteFetcher()
        self.liq_fetcher = LiquidityFetcher(primary_netuid=self.config.netuid)
        self.reward_calc = RewardCalculator()

    # ---------------------------------------------------- #
    # **LOGIC** – one iteration of business work
    # ---------------------------------------------------- #
    async def forward(self):
        return await forward(self)

    # ---------------------------------------------------- #
    # Main loop (simplified)
    # ---------------------------------------------------- #
    def run(self):  # noqa: D401
        bt.logging.warning(
            f"Validator starting at block {self.block:,} (netuid {self.config.netuid})"
        )

        async def _loop():
            while not self.should_exit:
                try:
                    # Sync wallet / metagraph and run business logic once
                    self.sync()
                    await self.forward()
                except Exception as err:
                    bt.logging.error(f"forward() raised: {err}")
                    bt.logging.debug("".join(traceback.format_exception(err)))
                    # brief backoff on error before scheduling the longer sleep
                    await asyncio.sleep(5)
                finally:
                    self.step += 1

                # Sleep a random time between 10 and 20 minutes
                sleep_s = random.uniform(10 * 60, 20 * 60)
                mins = int(sleep_s // 60)
                secs = int(sleep_s % 60)
                bt.logging.warning(
                    f"[sleep] Sleeping {mins}m {secs:02d}s before next iteration…"
                )
                await asyncio.sleep(sleep_s)

        # Ensure we have an event loop suitable for this thread
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self.loop = loop

        try:
            self.loop.run_until_complete(_loop())
        except KeyboardInterrupt:
            getattr(self, "axon", bt.logging).stop()
            bt.logging.success("Validator stopped by keyboard interrupt.")


# ──────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    with OceansValidator() as validator:
        while True:
            bt.logging.info(f"Validator running... {time.time()}")
            time.sleep(5)
