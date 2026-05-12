from typing import (
    Optional,
)
from datetime import (
    UTC,
    datetime,
)
from sqlalchemy.orm import (
    Session,
)
from subnet_validator.constants import (
    SiteStatus,
    CouponStatus,
)
from subnet_validator.database.entities import (
    Site,
    Coupon,
)
from subnet_validator.clients.supervisor_client import Site as SupervisorSite
from fiber.logging_utils import get_logger


logger = get_logger(__name__)


class SiteService:
    """
    Service for adding or updating Site records in the database.
    """

    def __init__(
        self,
        db: Session,
    ):
        self.db = db

    def add_or_update_site(
        self,
        store_id: int,
        store_domain: str,
        store_status: int,
        miner_hotkey: str | None = None,
        config: dict | None = None,
        api_url: str | None = None,
        total_coupon_slots: int = 15,
    ) -> Site:
        """
        Add a new site or update an existing one by id.
        If the site exists, update its base_url and status. Otherwise, create a new site.
        Returns the Site instance.
        """
        status = SiteStatus(store_status)
        site = self.db.query(Site).filter(Site.id == store_id).first()
        if site:
            previous_status = site.status
            site.base_url = store_domain
            site.status = status
            site.miner_hotkey = miner_hotkey
            site.config = config
            site.api_url = api_url
            site.total_coupon_slots = total_coupon_slots
            # Calculate available slots based on current coupon count
            self.update_available_slots(store_id)
            # If site transitions from ACTIVE to non-active (PENDING or INACTIVE),
            # immediately move VALID coupons to PENDING so they are revalidated ASAP.
            if (
                previous_status == SiteStatus.ACTIVE
                and status != SiteStatus.ACTIVE
            ):
                self.db.query(Coupon).filter(
                    Coupon.site_id == store_id,
                    Coupon.status == CouponStatus.VALID,
                ).update(
                    {
                        Coupon.status: CouponStatus.PENDING,
                        Coupon.last_checked_at: datetime.now(UTC),
                    },
                    synchronize_session=False,
                )
        else:
            site = Site(
                id=store_id,
                base_url=store_domain,
                status=status,
                miner_hotkey=miner_hotkey,
                config=config,
                api_url=api_url,
                total_coupon_slots=total_coupon_slots,
                available_slots=total_coupon_slots,
            )
            self.db.add(site)
        self.db.flush()
        return site

    def get_site_with_slots(self, site_id: int) -> Optional[Site]:
        """
        Get a site by ID with calculated available slots.
        Returns the Site instance or None if not found.
        """
        site = self.db.query(Site).filter(Site.id == site_id).first()
        if site:
            # Calculate actual available slots based on current coupon count
            active_coupons = (
                self.db.query(Coupon)
                .filter(
                    Coupon.site_id == site_id,
                    Coupon.status.in_(
                        [CouponStatus.VALID, CouponStatus.PENDING]
                    ),
                    Coupon.deleted_at.is_(None),
                )
                .count()
            )
            site.available_slots = max(
                0, site.total_coupon_slots - active_coupons
            )
        return site

    def update_available_slots(self, site_id: int) -> None:
        """
        Update the available slots count for a site based on current coupon status.
        """
        site = self.db.query(Site).filter(Site.id == site_id).first()
        if site:
            active_coupons = (
                self.db.query(Coupon)
                .filter(
                    Coupon.site_id == site_id,
                    Coupon.status.in_(
                        [CouponStatus.VALID, CouponStatus.PENDING]
                    ),
                    Coupon.deleted_at.is_(None),
                )
                .count()
            )
            site.available_slots = max(
                0, site.total_coupon_slots - active_coupons
            )
            self.db.flush()

    def can_submit_coupon(self, site_id: int) -> bool:
        """
        Check if a site can accept new coupon submissions.
        Returns True if there are available slots, False otherwise.
        """
        site = self.get_site_with_slots(site_id)
        if not site:
            return False
        return site.available_slots > 0

    def get_sites_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """
        Get paginated list of sites with calculated slot information.

        Args:
            page: Page number (1-based)
            page_size: Number of sites per page (max 100)

        Returns:
            Dictionary with pagination info and sites data
        """
        # Validate pagination parameters
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > 100:
            page_size = 100

        # Calculate offset
        offset = (page - 1) * page_size

        # Get total count
        total_sites = self.db.query(Site).count()

        # Get paginated sites
        sites = (
            self.db.query(Site)
            .order_by(Site.id.asc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        # Calculate slots for each site
        sites_info = []
        for site in sites:
            sites_info.append(
                {
                    "id": site.id,
                    "base_url": site.base_url,
                    "status": site.status,
                    "miner_hotkey": site.miner_hotkey,
                    "api_url": site.api_url,
                    "total_coupon_slots": site.total_coupon_slots,
                    "available_slots": site.available_slots,
                    "can_submit_coupon": site.available_slots > 0,
                }
            )

        # Calculate pagination info
        total_pages = (total_sites + page_size - 1) // page_size
        has_next_page = page < total_pages
        has_prev_page = page > 1

        return {
            "sites": sites_info,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_sites": total_sites,
                "total_pages": total_pages,
                "has_next_page": has_next_page,
                "has_prev_page": has_prev_page,
            },
        }

    def add_sites(self, sites: list[SupervisorSite]) -> int:
        """
        Add or update multiple sites in bulk.

        Args:
            sites: List of site objects with attributes:
                - store_id: int
                - store_domain: str
                - store_status: int
                - miner_hotkey: str | None
                - config: dict | None
                - api_url: str | None
                - total_coupon_slots: int (default 15)

        Returns:
            int: Number of sites successfully processed
        """
        processed = 0

        for site in sites:
            try:
                self.add_or_update_site(
                    store_id=site.store_id,
                    store_domain=site.store_domain,
                    store_status=site.store_status,
                    miner_hotkey=site.miner_hotkey,
                    config=site.config,
                    api_url=site.api_url,
                    total_coupon_slots=site.total_coupon_slots,
                )
                processed += 1
            except Exception as e:
                # Log error but continue with other sites
                logger.error(f"Failed to add/update site {site.store_id}: {e}")
                continue

        # Commit all changes at once
        self.db.commit()
        return processed
