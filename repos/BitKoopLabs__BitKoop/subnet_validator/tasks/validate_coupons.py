import asyncio
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from collections import (
    defaultdict,
)

from subnet_validator.settings import Settings

from .. import (
    dependencies,
)
from ..constants import (
    CouponStatus,
    SiteStatus,
)
from ..services.coupon_service import (
    CouponService,
)
from ..database.entities import (
    Site,
    Coupon,
)
from fiber.logging_utils import (
    get_logger,
)

logger = get_logger(__name__)


async def _validate_coupons_by_status(
    coupon_service: CouponService,
    settings: Settings,
    status: CouponStatus,
    last_checked_to=None,
):
    logger.info(
        f"Starting validation for coupons with status={status} and last_checked_to={last_checked_to}"
    )
    # Use the existing method with site_status filter to only get coupons from active sites
    coupons = coupon_service.get_coupons(
        status=status,
        last_checked_to=last_checked_to,
        site_status=SiteStatus.ACTIVE,
    )
    logger.info(f"Fetched {len(coupons)} coupons for validation from active sites only.")
    coupons_by_site = defaultdict(list)
    for coupon in coupons:
        coupons_by_site[coupon.site_id].append(coupon)
    for (
        site_id,
        coupons,
    ) in coupons_by_site.items():
        logger.info(f"Processing {len(coupons)} coupons for site_id={site_id}")
        site = coupon_service.db.query(Site).filter(Site.id == site_id).first()
        if not site:
            logger.warning(
                f"Site config not found for site_id={site_id}. Skipping validation. Pay attention to this site in the future."
            )
            continue
        try:
            validator = dependencies.get_coupon_validator(site, settings, coupon_service, coupon_service.metagraph)
        except ValueError as e:
            logger.error(
                f"Error getting coupon validator for site_id={site_id}: {e}"
            )
            continue
        try:
            results = await validator.validate(coupons)
            valid_count = sum(1 for _, ok in results if ok)
            invalid_count = len(results) - valid_count
            logger.info(
                f"Site {site_id}: {valid_count} coupons VALID, {invalid_count} coupons INVALID."
            )
        except Exception as e:
            logger.error(
                f"Error validating coupons for site_id={site_id}: {e}"
            )
            for coupon in coupons:
                coupon.status = CouponStatus.INVALID
                coupon.last_checked_at = datetime.now(UTC)
                logger.info(
                    f"Coupon {coupon.id} marked as INVALID due to validation error."
                )
        # Update available slots for the site after status changes
        coupon_service.update_slots_for_site(site_id)

        coupon_service.db.commit()
    logger.info(f"Finished validation for status={status}.")


async def validate_pending_coupons(
    coupon_service: CouponService, context=None, **kwargs
):
    # Use context.get_settings() if available, otherwise fallback to direct call
    if context:
        settings = context.get_settings()
    else:
        from . import dependencies

        settings = dependencies.get_settings()

    logger.info("Running validate_pending_coupons task.")
    await _validate_coupons_by_status(
        coupon_service,
        settings,
        CouponStatus.PENDING,
    )
    logger.info("Completed validate_pending_coupons task.")


async def validate_outdated_coupon(
    coupon_service: CouponService,
    context=None,
    **kwargs,
):
    # Use context.get_settings() if available, otherwise fallback to direct call
    if context:
        settings = context.get_settings()
    else:
        from . import dependencies

        settings = dependencies.get_settings()

    offset = settings.recheck_interval

    logger.info("Running validate_outdated_coupon task.")
    last_checked_to = datetime.now(UTC) - offset
    await _validate_coupons_by_status(
        coupon_service,
        settings,
        CouponStatus.VALID,
        last_checked_to=last_checked_to,
    )
    logger.info("Completed validate_outdated_coupon task.")


if __name__ == "__main__":
    settings = dependencies.get_settings()
    coupon_service = dependencies.get_coupon_service(
        db=next(dependencies.get_db()),
        settings=settings,
    )

    async def periodic_validate():
        while True:
            logger.info("Starting periodic coupon validation cycle.")
            await validate_pending_coupons(coupon_service, settings)
            await validate_outdated_coupon(coupon_service, settings)
            logger.info(
                f"Sleeping for {settings.validate_coupons_interval.total_seconds()} seconds before next cycle."
            )
            await asyncio.sleep(
                settings.validate_coupons_interval.total_seconds()
            )

    asyncio.run(periodic_validate())
