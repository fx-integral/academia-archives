import os
import asyncio
from datetime import UTC, datetime

import pytest

from subnet_validator.database.entities import Site, Coupon
from subnet_validator.constants import CouponAction
from subnet_validator.services.validator.api_coupon_validator import (
    ApiCouponValidator,
)


INTEGRATION_SITES = [
    {
        "domain": "bitkoop-test-2.myshopify.com",
        "api_url": "https://bitkoop-test-2.myshopify.com/apps/coupon-check?code={CODE}",
        "valid_codes": [
            "TEST-N-5",
            "TEST-N-4",
            "TEST-U-4",
            "TEST-M-5",
        ],
    },
    {
        "domain": "bitkoop-test-store.myshopify.com",
        "api_url": "https://bitkoop-test-store.myshopify.com/apps/coupon-check?code={CODE}",
        "valid_codes": [
            "Test",
            "Welcome",
            "ROMA",
            "Hello",
        ],
    },
]

INVALID_CODES = [
    "1234",
    "asasd",
    "two",
]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_coupon_validator_integration_real_shops_with_known_codes():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip(
            "Set RUN_INTEGRATION=1 to run integration tests against real Shopify stores"
        )

    storefront_password = os.getenv("SHOPIFY_STOREFRONT_PASSWORD", "1")

    for idx, site_info in enumerate(INTEGRATION_SITES, start=1):
        site = Site(
            id=idx,
            base_url=f"https://{site_info['domain']}",
            config={},
            api_url=site_info["api_url"],
        )
        validator = ApiCouponValidator(
            site, storefront_password=storefront_password
        )

        # Validate known valid codes
        for code in site_info["valid_codes"]:
            coupon = Coupon(
                code=code,
                site_id=site.id,
                miner_hotkey="5HIntegrationHotkey",
                source_hotkey="5SIntegrationSource",
                last_action=CouponAction.CREATE,
                last_action_date=int(datetime.now(UTC).timestamp() * 1000),
                last_action_signature="cafebabe",
            )
            res = await validator.validate([coupon])
            assert len(res) == 1
            _, is_valid = res[0]
            assert (
                is_valid is True
            ), f"Expected valid for {site_info['domain']} code={code}"

        # Validate common invalid codes
        for code in INVALID_CODES:
            coupon = Coupon(
                code=code,
                site_id=site.id,
                miner_hotkey="5HIntegrationHotkey",
                source_hotkey="5SIntegrationSource",
                last_action=CouponAction.CREATE,
                last_action_date=int(datetime.now(UTC).timestamp() * 1000),
                last_action_signature="cafebabe",
            )
            res = await validator.validate([coupon])
            assert len(res) == 1
            _, is_valid = res[0]
            assert (
                is_valid is False
            ), f"Expected invalid for {site_info['domain']} code={code}"
