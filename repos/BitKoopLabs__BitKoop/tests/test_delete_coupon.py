from datetime import UTC, datetime
import json
import os
from bittensor_wallet import (
    Wallet,
)
from fastapi.testclient import (
    TestClient,
)
from subnet_validator.constants import CouponAction
from subnet_validator.main import (
    app,
)
from subnet_validator.models import CouponTypedActionRequest


client = TestClient(app)


def test_delete_coupon():
    wallet = Wallet(
        os.getenv("WALLET_NAME"),
        os.getenv("HOTKEY_NAME"),
    )
    # First, submit a coupon to ensure it exists
    payload = {
        "site_id": 1,
        "code": "DELETECOUPON12",
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
    submit_response = client.put(
        "/coupons",
        json=payload,
        headers={"X-Signature": signature.hex()},
    )
    submit_response_json = submit_response.json()
    print(submit_response_json)
    assert (
        submit_response.status_code == 200
        or submit_response_json["detail"]
        == f"Coupon code {payload['code']} already exists."
    )

    # Now, delete the coupon
    delete_payload = {
        "site_id": payload["site_id"],
        "code": payload["code"],
        "hotkey": wallet.hotkey.ss58_address,
        "submitted_at": datetime.now(UTC).isoformat(),
    }
    typed_action_payload = CouponTypedActionRequest(
        hotkey=wallet.hotkey.ss58_address,
        site_id=payload["site_id"],
        code=payload["code"],
        submitted_at=delete_payload["submitted_at"],
        action=CouponAction.DELETE,
    )
    delete_payload_json = json.dumps(
        typed_action_payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )
    delete_signature = wallet.hotkey.sign(delete_payload_json)
    delete_response = client.post(
        "/coupons/delete",
        json=delete_payload,
        headers={"X-Signature": delete_signature.hex()},
    )
    print(delete_response.json())
    assert delete_response.status_code == 200
    data = delete_response.json()
    assert data["coupon_id"] == submit_response_json["coupon_id"]
