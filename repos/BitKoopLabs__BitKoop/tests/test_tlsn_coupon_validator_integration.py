import os
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from subnet_validator.services.validator.tlsn_coupon_validator import (
    TlsnCouponValidator,
)


RUNS = os.getenv("RUN_TLSN_INTEGRATION") == "1"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUNS,
    reason="Set RUN_TLSN_INTEGRATION=1 to run this test against a live miner",
)
async def test_tlsn_validator_live_miner_flow():
    """
    Live integration test that talks to a real miner server and exercises the TLSN flow.

    Requirements (env):
      - WALLET_NAME, HOTKEY_NAME: validator keypair to sign miner requests
      - Optional TLSN_VERIFIER_URL: override local verifier URL
      - RUN_TLSN_INTEGRATION=1 to enable
    """

    # Configure target miner server and hotkey
    miner_host = os.getenv("TLSN_TEST_MINER_HOST", "91.98.27.57")
    miner_port = int(os.getenv("TLSN_TEST_MINER_PORT", "8000"))
    miner_hotkey = os.getenv(
        "TLSN_TEST_MINER_HOTKEY",
        "5GjoBBeXGPcSDYjRycsRdkZKheaSRzmaXoKKMpmTGGx3w6px",
    )

    # Minimal settings object with required attributes
    class _Settings:
        def __init__(self):
            self.wallet_name = os.getenv("WALLET_NAME", "default")
            self.hotkey_name = os.getenv(
                "HOTKEY_NAME", os.getenv("WALLET_HOTKEY", "default")
            )
            self.tlsn_verifier_url = os.getenv(
                "TLSN_VERIFIER_URL", "http://127.0.0.1:8080/verify"
            )
            self.default_wait_interval = timedelta(seconds=2)
            # Keep test short
            self.lose_ownership_delta = timedelta(seconds=10)

    settings = _Settings()

    # Fake metagraph service that returns node with ip/port
    class _Metagraph:
        def get_node_by_hotkey(self, _hotkey):
            return SimpleNamespace(ip=miner_host, port=miner_port)

    # Fake coupon service with noop ownership clear
    class _CouponService:
        def _clear_coupon_ownership(self, site_id: int, code: str):
            return None

    # Minimal site and coupon objects (duck-typed)
    site = SimpleNamespace(id=21)
    coupon = SimpleNamespace(
        code=os.getenv("TLSN_TEST_COUPON_CODE", "TLSNTest"),
        site_id=site.id,
        miner_hotkey=miner_hotkey,
        last_checked_at=None,
        status=None,
    )

    validator = TlsnCouponValidator(
        site=site,
        verifier_url=settings.tlsn_verifier_url,
        settings=settings,
        metagraph=_Metagraph(),
        coupon_service=_CouponService(),
    )

    results = await validator.validate([coupon])

    assert isinstance(results, list)
    assert len(results) == 1
    # We at least expect that last_checked_at is set and a boolean result provided in tuple
    _coupon, is_valid = results[0]
    assert getattr(_coupon, "last_checked_at") is not None
    assert (
        isinstance(is_valid, bool)
        or is_valid is False
        or is_valid is True
        or is_valid is None
    )
