import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fiber.logging_utils import get_logger

from . import __version__ as version, APP_TITLE, dependencies
from .routes import coupons, info, sites, test, weights
from .context import AppContext
from .startup import (
    ensure_netuid_set,
    patch_metagraph,
    build_app_context,
    start_metagraph_sync,
    initialize_sync_progress,
)
from .background_tasks import (
    start_set_weights_thread,
    start_sync_sites_thread,
    start_validate_coupons_thread,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    context = None

    try:
        ensure_netuid_set()
        patch_metagraph()

        # Build application context with factory config
        context = build_app_context()

        sync_thread = start_metagraph_sync(context.metagraph)
        initialize_sync_progress(context)

        # Start set_weights background worker
        set_weights_thread, set_weights_stop = start_set_weights_thread(
            context
        )

        # Start sync_sites background worker
        sync_sites_thread, sync_sites_stop = start_sync_sites_thread(context)

        # Start validate_coupons background worker
        validate_coupons_thread, validate_coupons_stop = (
            start_validate_coupons_thread(context)
        )

        logger.info("Application startup complete")

    except Exception as e:
        logger.error(f"Startup failed: {e}")
        if context:
            context.close()
        raise

    yield

    # Shutdown
    logger.info("Shutting down...")
    try:
        context.metagraph.shutdown()
        if sync_thread is not None:
            logger.info("Joining metagraph sync thread...")
            sync_thread.join()
        # Stop and join set_weights thread
        try:
            set_weights_stop.set()  # type: ignore[name-defined]
            if set_weights_thread is not None:  # type: ignore[name-defined]
                logger.info("Joining set_weights worker thread...")
                set_weights_thread.join()
        except NameError:
            pass

        # Stop and join sync_sites thread
        try:
            sync_sites_stop.set()  # type: ignore[name-defined]
            if sync_sites_thread is not None:  # type: ignore[name-defined]
                logger.info("Joining sync_sites worker thread...")
                sync_sites_thread.join()
        except NameError:
            pass

        # Stop and join validate_coupons thread
        try:
            validate_coupons_stop.set()  # type: ignore[name-defined]
            if validate_coupons_thread is not None:  # type: ignore[name-defined]
                logger.info("Joining validate_coupons worker thread...")
                validate_coupons_thread.join()
        except NameError:
            pass

        # Clean up context
        if context:
            context.close()

        logger.info("Shutdown complete")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


def _create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    subtensor_network = os.getenv("SUBTENSOR_NETWORK")

    app = FastAPI(
        title=APP_TITLE,
        description="API for validating coupon codes and managing miner sessions",
        version=version,
        lifespan=lifespan,
        docs_url=None if subtensor_network == "finney" else "/docs",
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, replace with specific origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


def _register_routers(app: FastAPI):
    """Register all application routers."""
    # Core routers
    app.include_router(coupons.router, prefix="/coupons", tags=["coupons"])
    app.include_router(info.router, prefix="/info", tags=["info"])
    app.include_router(sites.router, prefix="/sites", tags=["sites"])

    # Test environment routers
    if os.getenv("ENV") == "test":
        app.include_router(test.router, prefix="/test", tags=["test"])
        app.include_router(weights.router, prefix="/weights", tags=["weights"])


# Create the application
app = _create_app()
_register_routers(app)
