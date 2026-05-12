import asyncio
from subnet_validator.clients.supervisor_client import (
    SupervisorApiClient,
)
from subnet_validator.settings import (
    Settings,
)
from subnet_validator.services.site_service import (
    SiteService,
)
from subnet_validator.database.database import (
    get_db,
)
from fiber.logging_utils import (
    get_logger,
)

logger = get_logger(__name__)


async def sync_sites(
    settings: Settings,
):
    logger.info("Syncing sites from supervisor API")
    processed = 0
    page = 1
    page_size = 100
    db_gen = get_db()
    db = next(db_gen)
    try:
        service = SiteService(db)
        async with SupervisorApiClient(
            settings.supervisor_api_url
        ) as api_client:
            while True:
                try:
                    sites = await api_client.get_sites(
                        page=page, page_size=page_size
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to fetch sites from supervisor API (page {page}): {e}"
                    )
                    break

                if not sites:
                    break

                for site in sites:
                    try:
                        service.add_or_update_site(
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
                        logger.error(
                            f"Failed to add/update site {site.store_id}: {e}"
                        )
                db.commit()

                if len(sites) < page_size:
                    break
                page += 1
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    logger.info(f"Processed {processed} sites.")


if __name__ == "__main__":
    settings = Settings()
    asyncio.run(sync_sites(settings))
