from datetime import UTC, datetime
import json
import os
from fastapi.testclient import (
    TestClient,
)
from subnet_validator.constants import CouponAction
from subnet_validator.main import (
    app,
)
from bittensor_wallet import (
    Wallet,
)

from subnet_validator.models import CouponTypedActionRequest

client = TestClient(app)


def test_submit_coupon():
    wallet = Wallet(
        os.getenv("WALLET_NAME"),
        os.getenv("HOTKEY_NAME"),
    )
    payload = {
        "site_id": 1,
        "code": "TESTCOUPON123",
        "category_id": 2,
        "restrictions": "None",
        "country_code": "US",
        "discount_value": "10%",
        "discount_percentage": 10,
        "is_global": True,
        "used_on_product_url": "https://example.com/product",
        "valid_until": "2030-01-01T00:00:00Z",
        "hotkey": wallet.hotkey.ss58_address,
        "submitted_at": int(datetime.now(UTC).timestamp() * 1000),
    }
    typed_action_payload = CouponTypedActionRequest(
        hotkey=wallet.hotkey.ss58_address,
        site_id=payload["site_id"],
        code=payload["code"],
        submitted_at=payload["submitted_at"],
        action=CouponAction.CREATE,
    )

    payload_json = json.dumps(
        typed_action_payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )
    signature = wallet.hotkey.sign(payload_json)

    response = client.put(
        "/coupons",
        json=typed_action_payload.model_dump(mode="json"),
        headers={"X-Signature": signature.hex()},
    )
    print(response.json())
    assert response.status_code == 200
    data = response.json()
    assert "coupon_id" in data
