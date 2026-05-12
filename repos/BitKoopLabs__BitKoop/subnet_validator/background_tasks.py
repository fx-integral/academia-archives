"""Background task management."""

import asyncio
import threading
from fiber.logging_utils import get_logger

from .context import AppContext

logger = get_logger(__name__)


def run_set_weights_loop(context: AppContext, stop_event: threading.Event):
    """Run periodic set_weights in its own thread using an asyncio loop."""

    async def _worker():
        # Import async set_weights to reuse existing logic
        from .tasks.set_weights import set_weights as async_set_weights
        from .database.database import get_db

        while not stop_event.is_set():
            # Create a new DB session for this thread
            db = next(get_db())
            try:
                # Create services with the thread's DB session
                services = context.create_services(db)

                await async_set_weights(db=db, context=context, **services)
            except Exception as e:
                logger.error(f"set_weights worker error: {e}")
            finally:
                db.close()

            # Sleep respecting stop_event
            settings = context.get_settings()
            total = settings.default_wait_interval.total_seconds()
            # Sleep in small chunks to react promptly to stop
            slept = 0
            step = min(5.0, total)
            while slept < total and not stop_event.is_set():
                await asyncio.sleep(step)
                slept += step

    asyncio.run(_worker())


def run_sync_sites_loop(context: AppContext, stop_event: threading.Event):
    """Run periodic sync_sites in its own thread using an asyncio loop."""

    async def _worker():
        from .clients.supervisor_client import SupervisorApiClient
        from .database.database import get_db

        while not stop_event.is_set():
            # Create a new DB session for this thread
            db = next(get_db())
            try:
                # Get settings dynamically
                settings = context.get_settings()

                logger.info("Syncing sites from supervisor API")
                processed = 0
                page = 1
                page_size = 100

                # Use services from context
                services = context.create_services(db)
                service = services["site_service"]
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

                        # Use the new add_sites method for bulk processing
                        processed += service.add_sites(sites)

                        if len(sites) < page_size:
                            break
                        page += 1

                logger.info(f"Processed {processed} sites.")

            except Exception as e:
                logger.error(f"sync_sites worker error: {e}")
            finally:
                db.close()

            # Sleep respecting stop_event
            settings = context.get_settings()
            total = settings.sync_sites_interval.total_seconds()
            # Sleep in small chunks to react promptly to stop
            slept = 0
            step = min(5.0, total)
            while slept < total and not stop_event.is_set():
                await asyncio.sleep(step)
                slept += step

    asyncio.run(_worker())


def start_set_weights_thread(
    context: AppContext,
) -> tuple[threading.Thread | None, threading.Event | None]:
    """Start background thread for periodically setting weights."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_set_weights_loop, args=(context, stop_event), daemon=True
    )
    thread.start()
    logger.info("Started set_weights worker thread")
    return thread, stop_event


def run_validate_coupons_loop(
    context: AppContext, stop_event: threading.Event
):
    """Run periodic validate_coupons in its own thread using an asyncio loop."""

    async def _worker():
        from .database.database import get_db
        from .tasks.validate_coupons import (
            validate_pending_coupons,
            validate_outdated_coupon,
        )

        while not stop_event.is_set():
            # Create a new DB session for this thread
            db = next(get_db())
            try:
                # Get settings dynamically
                settings = context.get_settings()

                logger.info("Starting coupon validation cycle")

                # Use services from context
                services = context.create_services(db)
                coupon_service = services["coupon_service"]

                # Run both validation tasks
                await validate_pending_coupons(
                    coupon_service=coupon_service,
                    context=context,
                )

                await validate_outdated_coupon(
                    coupon_service=coupon_service,
                    context=context,
                )

                logger.info("Completed coupon validation cycle")

            except Exception as e:
                logger.error(f"validate_coupons worker error: {e}")
            finally:
                db.close()

            # Sleep respecting stop_event
            settings = context.get_settings()
            total = settings.validate_coupons_interval.total_seconds()
            # Sleep in small chunks to react promptly to stop
            slept = 0
            step = min(5.0, total)
            while slept < total and not stop_event.is_set():
                await asyncio.sleep(step)
                slept += step

    asyncio.run(_worker())


def start_set_weights_thread(
    context: AppContext,
) -> tuple[threading.Thread | None, threading.Event | None]:
    """Start background thread for periodically setting weights."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_set_weights_loop, args=(context, stop_event), daemon=True
    )
    thread.start()
    logger.info("Started set_weights worker thread")
    return thread, stop_event


def start_sync_sites_thread(
    context: AppContext,
) -> tuple[threading.Thread | None, threading.Event | None]:
    """Start background thread for periodically syncing sites."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_sync_sites_loop, args=(context, stop_event), daemon=True
    )
    thread.start()
    logger.info("Started sync_sites worker thread")
    return thread, stop_event


def start_validate_coupons_thread(
    context: AppContext,
) -> tuple[threading.Thread | None, threading.Event | None]:
    """Start background thread for periodically validating coupons."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_validate_coupons_loop,
        args=(context, stop_event),
        daemon=True,
    )
    thread.start()
    logger.info("Started validate_coupons worker thread")
    return thread, stop_event
