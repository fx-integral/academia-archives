from datetime import (
    UTC,
    datetime,
)
from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Integer,
    String,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from ..constants import (
    CouponStatus,
    CouponAction,
    SiteStatus,
)


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )
    base_url: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    status: Mapped[SiteStatus] = mapped_column(
        Integer,
        default=SiteStatus.ACTIVE,
        nullable=False,
    )
    config: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    miner_hotkey: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    api_url: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    # Slot management for coupon submission
    total_coupon_slots: Mapped[int] = mapped_column(
        Integer,
        default=15,
        nullable=False,
    )
    available_slots: Mapped[int] = mapped_column(
        Integer,
        default=15,
        nullable=False,
    )
    coupons: Mapped[list["Coupon"]] = relationship(
        "Coupon",
        back_populates="site",
    )


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    coupons: Mapped[list["Coupon"]] = relationship(
        "Coupon",
        back_populates="category",
    )


class Coupon(Base):
    __tablename__ = "coupons"

    code: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        nullable=False,
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id"),
        primary_key=True,
        nullable=False,
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"),
        nullable=True,
    )
    category: Mapped[Category] = relationship(
        "Category",
        back_populates="coupons",
    )
    used_on_product_url: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    restrictions: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    country_code: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    discount_value: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    discount_percentage: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    is_global: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    # New: store Shopify rule JSON as-is from API response
    rule: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[CouponStatus] = mapped_column(
        Integer,
        default=CouponStatus.PENDING,
        nullable=False,
    )

    source_hotkey: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    miner_hotkey: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        nullable=False,
    )
    miner_coldkey: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    use_coldkey_for_signature: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    last_action: Mapped[CouponAction] = mapped_column(
        Integer,
        default=CouponAction.CREATE,
        nullable=False,
    )
    last_action_date: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    last_action_signature: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    site: Mapped[Site] = relationship(
        "Site",
        back_populates="coupons",
    )

    @property
    def id(self) -> str:
        """Synthetic identifier derived from the composite primary key.
        Useful for API responses and code paths that previously relied on integer IDs.
        """
        return f"{self.site_id}:{self.code}:{self.miner_hotkey}"


class ValidatorSyncOffset(Base):
    __tablename__ = "validator_sync_offset"
    hotkey: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )
    last_coupon_action_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_sync_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class MetagraphNode(Base):
    __tablename__ = "metagraph_nodes"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    hotkey: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    coldkey: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    netuid: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    alpha_stake: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    tao_stake: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    stake: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    ip: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    ip_type: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    protocol: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    port: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    validator_version: Mapped[str] = mapped_column(
        String,
        nullable=True,
    )
    is_enough_weight: Mapped[bool] = mapped_column(
        Boolean,
        nullable=True,
    )


class DynamicConfig(Base):
    __tablename__ = "dynamic_config"
    key: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )
    value: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )


class CouponActionLog(Base):
    __tablename__ = "coupon_action_logs"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    # Composite foreign key to coupons
    code: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    site_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    miner_hotkey: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    action: Mapped[CouponAction] = mapped_column(
        Integer,
        nullable=False,
    )
    action_date: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    signature: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    source_hotkey: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["code", "site_id", "miner_hotkey"],
            ["coupons.code", "coupons.site_id", "coupons.miner_hotkey"],
        ),
    )


class CouponOwnership(Base):
    __tablename__ = "coupon_ownerships"

    # One ownership record per unique (site, code)
    code: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        nullable=False,
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id"),
        primary_key=True,
        nullable=False,
    )

    # The hotkey that currently owns this coupon code on the site
    # Can be None when ownership is cleared (for debugging/audit purposes)
    owner_hotkey: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_contested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    contest_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
