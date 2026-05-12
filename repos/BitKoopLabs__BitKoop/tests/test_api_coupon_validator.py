import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from subnet_validator.database.entities import Site, Coupon
from subnet_validator.constants import CouponStatus, CouponAction
from subnet_validator.services.validator.api_coupon_validator import (
    ApiCouponValidator,
)


@pytest.mark.asyncio
async def test_api_coupon_validator_valid_response():
    # Arrange site and coupon
    site = Site(
        id=1,
        base_url="https://bitkoop-test-store.myshopify.com",
        config={"storefront_password": "1"},
        api_url="https://bitkoop-test-store.myshopify.com/apps/coupon-check?code={CODE}",
    )
    coupon = Coupon(
        code="Test",
        site_id=site.id,
        miner_hotkey="5F...",
        source_hotkey="5S...",
        last_action=CouponAction.CREATE,
        last_action_date=int(datetime.now(UTC).timestamp() * 1000),
        last_action_signature="deadbeef",
    )

    # Prepare mocked transport
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/password") and request.method == "GET":
            html = """
            <html><body>
              <form method="post">
                <input type="hidden" name="utf8" value="✓" />
                <input type="hidden" name="form_type" value="storefront_password" />
                <input type="password" name="password" value="" />
              </form>
            </body></html>
            """
            return httpx.Response(200, text=html)
        if url.endswith("/password") and request.method == "POST":
            return httpx.Response(200, text="ok")
        if url.endswith("/") and request.method == "GET":
            # Landing on home page means not redirected to /password
            return httpx.Response(200, text="home")
        if "/apps/coupon-check?code=Test" in url and request.method == "GET":
            body = {
                "ok": True,
                "shop": "bitkoop-test-store.myshopify.com",
                "code": "Test",
                "applicable": True,
                "status": "active",
                "ts": datetime.now(UTC).isoformat(),
            }
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    validator = ApiCouponValidator(site)

    # Monkeypatch client creation to use our mock transport
    async def _get_or_create_client_override():
        if validator._client is None:
            validator._client = httpx.AsyncClient(
                transport=transport, follow_redirects=True
            )
        return validator._client

    validator._get_or_create_client = _get_or_create_client_override  # type: ignore

    # Act
    results = await validator.validate([coupon])

    # Assert
    assert len(results) == 1
    c, is_valid = results[0]
    assert c is coupon
    assert is_valid is True
    assert coupon.status == CouponStatus.VALID
    assert coupon.last_checked_at is not None


@pytest.mark.asyncio
async def test_api_coupon_validator_invalid_response():
    site = Site(
        id=1,
        base_url="https://bitkoop-test-store.myshopify.com",
        config={"storefront_password": "1"},
        api_url="https://bitkoop-test-store.myshopify.com/apps/coupon-check?code={CODE}",
    )
    coupon = Coupon(
        code="1234",
        site_id=site.id,
        miner_hotkey="5F...",
        source_hotkey="5S...",
        last_action=CouponAction.CREATE,
        last_action_date=int(datetime.now(UTC).timestamp() * 1000),
        last_action_signature="deadbeef",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/password") and request.method == "GET":
            html = """
            <html><body>
              <form method="post">
                <input type="hidden" name="utf8" value="✓" />
                <input type="hidden" name="form_type" value="storefront_password" />
                <input type="password" name="password" value="" />
              </form>
            </body></html>
            """
            return httpx.Response(200, text=html)
        if url.endswith("/password") and request.method == "POST":
            return httpx.Response(200, text="ok")
        if url.endswith("/") and request.method == "GET":
            return httpx.Response(200, text="home")
        if "/apps/coupon-check?code=1234" in url and request.method == "GET":
            body = {
                "ok": True,
                "shop": "bitkoop-test-store.myshopify.com",
                "code": "1234",
                "status": "invalid",
                "applicable": False,
                "reason": "Not found in Shopify",
                "ts": datetime.now(UTC).isoformat(),
                "source": "cache",
            }
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    validator = ApiCouponValidator(site)

    async def _get_or_create_client_override():
        if validator._client is None:
            validator._client = httpx.AsyncClient(
                transport=transport, follow_redirects=True
            )
        return validator._client

    validator._get_or_create_client = _get_or_create_client_override  # type: ignore

    results = await validator.validate([coupon])

    assert len(results) == 1
    c, is_valid = results[0]
    assert c is coupon
    assert is_valid is False
    assert coupon.status == CouponStatus.INVALID
    assert coupon.last_checked_at is not None
