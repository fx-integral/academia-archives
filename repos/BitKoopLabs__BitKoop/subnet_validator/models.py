from pydantic import (
    BaseModel,
    ConfigDict,
    HttpUrl,
    Field,
    field_validator,
    computed_field,
)
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Optional,
)
from pydantic_core import PydanticCustomError
from scalecodec.utils.ss58 import (
    ss58_decode,
)
import pycountry

from subnet_validator.constants import CouponAction, CouponStatus
import re


class HotkeyRequest(BaseModel):
    hotkey: str
    coldkey: Optional[str] = None
    use_coldkey_for_signature: Optional[bool] = None

    @field_validator("hotkey", "coldkey")
    @classmethod
    def validate_ss58_address(
        cls,
        v,
    ):
        if v is None:
            return v
        try:
            ss58_decode(v)
        except Exception:
            raise PydanticCustomError(
                "value_error",
                "Invalid ss58 address",
            )
        return v
    
    model_config = ConfigDict(extra="allow", json_dumps_kwargs={"ensure_ascii": False})


class CouponActionRequest(HotkeyRequest):
    site_id: int
    code: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )
    submitted_at: int = Field(
        help="Unix timestamp in milliseconds",
        gt=0,
    )

    @field_validator("code")
    @classmethod
    def validate_code_rules(cls, v):
        """Validate coupon code according to rules:
        - allow letters of any language and digits
        - allow special symbols except URL-reserved: / ? # [ ] @ ! $ & ' ( ) * + , ; =
        - forbid any whitespace characters
        - max length enforced by Field
        """
        # Forbid any whitespace anywhere
        if any(ch.isspace() for ch in v):
            raise PydanticCustomError(
                "value_error",
                "Coupon code must not contain whitespace",
            )

        # Forbid URL-reserved characters
        reserved = set("/?#[]@!$&'()*+,;=")
        if any(ch in reserved for ch in v):
            raise PydanticCustomError(
                "value_error",
                "Coupon code contains forbidden URL-reserved characters",
            )

        return v

    def get_submitted_at_datetime(self) -> datetime:
        """Convert submitted_at string to datetime object."""
        return datetime.fromtimestamp(self.submitted_at / 1000, UTC)


class CouponTypedActionRequest(CouponActionRequest):
    action: CouponAction


class CouponSubmitRequest(CouponActionRequest):
    category_id: Optional[int] = None
    restrictions: Optional[str] = Field(
        None,
        min_length=1,
        max_length=1000,
    )
    country_code: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
    )
    discount_value: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
    )
    discount_percentage: Optional[int] = Field(
        None,
        ge=0,
        le=100,
    )
    is_global: Optional[bool] = None
    used_on_product_url: Optional[HttpUrl] = Field(None)
    valid_until: Optional[str] = None

    @field_validator("country_code")
    @classmethod
    def validate_country_code(
        cls,
        v,
    ):
        if v is None:
            return v
        if pycountry.countries.get(alpha_2=v.upper()) is None:
            raise PydanticCustomError(
                "value_error",
                "Must be a valid ISO 3166-1 alpha-2 code",
            )
        return v.upper()

    @field_validator("valid_until")
    @classmethod
    def validate_valid_until(
        cls,
        v,
    ):
        if v is None:
            return v
        try:
            # Parse ISO format datetime string
            valid_until_datetime = datetime.fromisoformat(v)
        except (TypeError, ValueError):
            raise PydanticCustomError(
                "value_error",
                "Must be a valid ISO format datetime string",
            )

        # Treat naive datetimes as UTC
        if valid_until_datetime.tzinfo is None:
            valid_until_datetime = valid_until_datetime.replace(tzinfo=UTC)

        if valid_until_datetime < datetime.now(UTC):
            raise PydanticCustomError(
                "value_error",
                "Must be in the future",
            )

        return v

    def get_valid_until_datetime(self) -> Optional[datetime]:
        """Convert valid_until string to datetime object."""
        if self.valid_until is None:
            return None
        value = self.valid_until
        # Normalize 'Z' suffix to '+00:00' for fromisoformat compatibility
        value = (
            value.replace("Z", "+00:00") if isinstance(value, str) else value
        )
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt


class CouponSubmitResponse(BaseModel):
    coupon_id: str
    is_new: bool


class CouponDeleteRequest(CouponActionRequest):
    pass


class CouponRecheckRequest(CouponActionRequest):
    pass


class CouponRecheckResponse(BaseModel):
    coupon_id: str


class CouponDeleteResponse(BaseModel):
    coupon_id: str


class CouponResponse(BaseModel):
    id: str
    code: str
    site_id: int
    category_id: Optional[int]
    used_on_product_url: Optional[str]
    restrictions: Optional[str]
    country_code: Optional[str]
    discount_value: Optional[str]
    discount_percentage: Optional[int]
    is_global: Optional[bool]
    status: CouponStatus
    source_hotkey: str
    miner_hotkey: str
    miner_coldkey: Optional[str]
    use_coldkey_for_signature: Optional[bool]
    valid_until: Optional[datetime]
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    last_checked_at: Optional[datetime]
    last_action: CouponAction
    last_action_date: int
    last_action_signature: str
    rule: Optional[dict]

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def last_action_at(self) -> datetime:
        """Computed field that converts last_action_date timestamp to datetime."""
        return datetime.fromtimestamp(self.last_action_date / 1000, UTC)
