from subnet_validator.database.entities import Coupon


class BaseCouponValidator:

    async def validate(self, coupons: list[Coupon]):
        pass
