from datetime import (
    UTC,
    datetime,
)
from subnet_validator.constants import (
    CouponStatus,
)
from subnet_validator.database.entities import (
    Coupon,
    Site,
)
import json
import os
import random

CONFIG_PATH = "data/config.json"


class CouponValidator:
    def __init__(
        self,
        site: Site,
    ):
        self.site = site
        self.site_config = self._load_site_config(site.id)

    def _load_site_config(
        self,
        site_id,
    ):
        try:
            with open(
                CONFIG_PATH,
                "r",
            ) as f:
                config = json.load(f)
            return config.get(
                "sites",
                {},
            ).get(
                str(site_id),
                {},
            )
        except Exception:
            return {}

    def _get_valid_probability(
        self,
    ):
        return self.site_config.get(
            "valid_coupon_probability",
            1.0,
        )

    async def validate(
        self,
        coupons: list[Coupon],
    ):
        results = []
        prob = self._get_valid_probability()
        for coupon in coupons:
            try:
                is_valid = random.random() < prob
                coupon.status = (
                    CouponStatus.VALID if is_valid else CouponStatus.INVALID
                )
                coupon.last_checked_at = datetime.now(UTC)
                results.append(
                    (
                        coupon,
                        is_valid,
                    )
                )
            except Exception:
                coupon.status = CouponStatus.INVALID
                coupon.last_checked_at = datetime.now(UTC)
                results.append(
                    (
                        coupon,
                        False,
                    )
                )
        return results
