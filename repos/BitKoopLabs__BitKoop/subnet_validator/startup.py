"""Application startup and shutdown logic."""

import os
import threading
from datetime import UTC, datetime
from fiber.logging_utils import get_logger

from . import dependencies
from .context import AppContext

logger = get_logger(__name__)


def ensure_netuid_set():
    """Ensure NETUID is set before building the miner configuration."""
    if "NETUID" not in os.environ:
        from . import dependencies

        settings = dependencies.get_settings()
        default_netuid = os.environ.get("NETUID", settings.netuid)
        if default_netuid:
            os.environ["NETUID"] = str(default_netuid)


def patch_metagraph():
    """Monkey-patch Metagraph to our extended version before factory_config() constructs it."""
    try:
        from subnet_validator.fiber_ext.metagraph import ExtendedMetagraph
        import fiber.chain.metagraph as mg

        mg.Metagraph = ExtendedMetagraph  # type: ignore[attr-defined]
        logger.info("Successfully patched Metagraph with ExtendedMetagraph")
    except Exception as e:
        logger.error(f"Failed to patch Metagraph with ExtendedMetagraph: {e}")
        raise


def build_app_context() -> AppContext:
    """Build the application context with shared resources (no DB sessions)."""
    from . import dependencies
    import httpx

    # Get factory config which contains both metagraph and substrate
    factory_config = dependencies.get_factory_config()

    # Initialize HTTP client for future external settings fetching
    http_client = httpx.AsyncClient(timeout=30.0)

    return AppContext(
        factory_config=factory_config,
        http_client=http_client,
    )


def start_metagraph_sync(metagraph):
    """Start the metagraph sync thread if substrate is available."""
    if metagraph.substrate is not None:
        sync_thread = threading.Thread(
            target=metagraph.periodically_sync_nodes, daemon=True
        )
        sync_thread.start()
        logger.info("Started metagraph sync thread")
        return sync_thread
    return None


def initialize_sync_progress(context: AppContext):
    """Initialize sync progress if not already set."""
    from .database.database import get_db

    db = next(get_db())
    try:
        services = context.create_services(db)

        # Use services as kwargs for cleaner code
        _initialize_sync_progress_impl(db=db, **services)
    except Exception as e:
        logger.error(f"Failed to initialize sync progress: {e}")
    finally:
        db.close()


def _initialize_sync_progress_impl(db, dynamic_config_service, **kwargs):
    """Internal implementation of sync progress initialization."""
    sync_progress = dynamic_config_service.get_sync_progress()
    if not sync_progress:
        dynamic_config_service.set_sync_progress(
            {
                "status": "pending",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )
        logger.info("Initialized sync progress")
