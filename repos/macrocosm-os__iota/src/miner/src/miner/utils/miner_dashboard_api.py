from collections import defaultdict
from pathlib import Path

# FastAPI imports
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from loguru import logger
from typing import Any, get_args
from common.utils.timer_logger import TIMER_NAMES

# ============================================================================
# FastAPI Visualization Server
# ============================================================================

# In-memory storage for events and counts
# Structure: {hotkey: [events]}
events_store: dict[str, list[dict[str, Any]]] = defaultdict(list)
# Structure: {hotkey: [count_logs]}
counts_store: dict[str, list[dict[str, Any]]] = defaultdict(list)
# Structure: {hotkey: {event_name: count}}
cumulative_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

# Maximum number of events to keep in memory per hotkey
MAX_EVENTS = 500
MAX_COUNT_LOGS = 1000

# Extract the list of timer names from the Literal type
TIMER_NAMES = list(get_args(TIMER_NAMES))

# Create FastAPI app
app = FastAPI(title="Timer Visualization Server")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/timer_names")
async def get_timer_names():
    """Get the list of available timer names."""
    return TIMER_NAMES


@app.get("/api/hotkeys")
async def get_hotkeys():
    """Get the list of available hotkeys."""
    return sorted(list(set(list(events_store.keys()) + list(counts_store.keys()))))


@app.get("/api/events/{hotkey}")
async def get_events(hotkey: str):
    """Get events for a specific hotkey."""
    if hotkey not in events_store:
        return []
    return events_store[hotkey]


@app.get("/api/counts/{hotkey}")
async def get_counts(hotkey: str):
    """Get count logs for a specific hotkey."""
    if hotkey not in counts_store:
        return []
    return counts_store[hotkey]


@app.post("/api/events/{hotkey}")
async def add_event(hotkey: str, event: dict[str, Any]):
    """Add an event for a specific hotkey."""
    logger.info(f"Adding event for hotkey: {hotkey} - {event}")
    events_store[hotkey].append(event)

    # Keep only the most recent events
    if len(events_store[hotkey]) > MAX_EVENTS:
        # Keep track of active event IDs (events with start but no end)
        active_event_ids = set()
        for e in events_store[hotkey]:
            if e.get("type") == "start":
                active_event_ids.add(e["id"])
            elif e.get("type") == "end":
                active_event_ids.discard(e["id"])

        # Keep recent events and any start events for active pairs
        recent_events = events_store[hotkey][-MAX_EVENTS:]
        events_to_keep = []
        for e in events_store[hotkey]:
            if e in recent_events or e["id"] in active_event_ids:
                events_to_keep.append(e)
        events_store[hotkey] = events_to_keep

    return {"status": "ok"}


@app.post("/api/counts/{hotkey}")
async def add_count_log(hotkey: str, count_log: dict[str, Any]):
    """Add a count log entry for a specific hotkey."""
    counts_store[hotkey].append(count_log)

    # Update cumulative counts
    if "event_counts" in count_log:
        cumulative_counts[hotkey].update(count_log["event_counts"])

    # Keep only the most recent count logs
    if len(counts_store[hotkey]) > MAX_COUNT_LOGS:
        counts_store[hotkey] = counts_store[hotkey][-MAX_COUNT_LOGS:]

    return {"status": "ok"}


@app.get("/api/stats/{hotkey}")
async def get_stats(hotkey: str):
    """Get statistics for a specific hotkey."""
    return {
        "event_count": len(events_store.get(hotkey, [])),
        "count_log_count": len(counts_store.get(hotkey, [])),
        "cumulative_counts": dict(cumulative_counts.get(hotkey, {})),
    }


@app.get("/vis.html")
async def get_visualization():
    """Serve the visualization HTML file."""
    # Try to find the vis.html file in the miner visualization directory
    current_file = Path(__file__).resolve()
    # current_file: .../src/miner/src/miner/utils/miner_dashboard_api.py
    # Go up to the miner package level
    miner_package = current_file.parent.parent  # .../src/miner/src/miner/

    # Try multiple possible locations
    possible_locations = [
        miner_package / "visualization" / "vis.html",
        Path.cwd() / "src" / "miner" / "src" / "miner" / "visualization" / "vis.html",
        Path.cwd() / "vis.html",
    ]

    for html_file in possible_locations:
        if html_file.exists():
            logger.info(f"Serving visualization from: {html_file}")
            return FileResponse(html_file)

    raise HTTPException(
        status_code=404, detail=f"Visualization file not found. Searched: {[str(p) for p in possible_locations]}"
    )


@app.get("/")
async def root():
    """Redirect to visualization."""
    return await get_visualization()


def start_visualization_server(port: int = 8007, host: str = "0.0.0.0", suppress_logs: bool = True):
    """
    Start the FastAPI visualization server.

    Args:
        port: Port to run the server on (default: 8007)
        host: Host to bind to (default: 0.0.0.0)
        suppress_logs: If True, suppress all logging output (default: True)

    Example:
        from common.utils.timer_logger import start_visualization_server
        start_visualization_server(port=8007)
    """
    import logging
    import sys

    # Variables for cleanup
    original_stdout = None
    original_stderr = None
    devnull_fd = None

    # Suppress all logging when running in dashboard mode (separate process)
    if suppress_logs:
        # Suppress loguru output - remove all handlers and add null sink
        logger.remove()
        logger.add(lambda _: None, level="DEBUG")

        # Suppress Python logging (uvicorn/FastAPI)
        logging.disable(logging.CRITICAL)
        uvicorn_logger = logging.getLogger("uvicorn")
        uvicorn_access_logger = logging.getLogger("uvicorn.access")
        fastapi_logger = logging.getLogger("fastapi")
        uvicorn_logger.setLevel(logging.CRITICAL)
        uvicorn_access_logger.setLevel(logging.CRITICAL)
        fastapi_logger.setLevel(logging.CRITICAL)
        # Remove handlers to prevent any output
        uvicorn_logger.handlers.clear()
        uvicorn_access_logger.handlers.clear()
        fastapi_logger.handlers.clear()

        # Redirect stdout/stderr to devnull to catch any remaining output
        # This prevents uvicorn from printing directly to terminal
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        try:
            import os

            devnull_fd = open(os.devnull, "w")
            sys.stdout = devnull_fd
            sys.stderr = devnull_fd
        except Exception:
            # Fallback: create a dummy file-like object that does nothing
            class NullWriter:
                def write(self, s):
                    pass

                def flush(self):
                    pass

                def close(self):
                    pass

            null_writer = NullWriter()
            sys.stdout = null_writer
            sys.stderr = null_writer
            devnull_fd = None  # Mark that we don't need to close
    else:
        # Normal logging mode - print startup messages
        logger.info(f"\n{'='*60}")
        logger.info("Timer Visualization Server Starting")
        logger.info(f"{'='*60}")
        logger.info(f"Server running at: http://localhost:{port}")
        logger.info(f"Open this URL in your browser: http://localhost:{port}/vis.html")
        logger.info("\nAPI Endpoints:")
        logger.info("  - GET  /api/timer_names - Get available timer names")
        logger.info("  - GET  /api/hotkeys - Get available hotkeys")
        logger.info("  - GET  /api/events/{hotkey} - Get events for hotkey")
        logger.info("  - GET  /api/counts/{hotkey} - Get count logs for hotkey")
        logger.info("  - POST /api/events/{hotkey} - Add event for hotkey")
        logger.info("  - POST /api/counts/{hotkey} - Add count log for hotkey")
        logger.info("\nPress Ctrl+C to stop the server")
        logger.info(f"{'='*60}\n")

    # Run the server in blocking mode
    # This is appropriate for running in a separate process
    try:
        uvicorn.run(app, host=host, port=port, log_level="critical")
    except Exception as e:
        if not suppress_logs:
            logger.exception(f"Error starting visualization server: {e}")
        raise
    finally:
        if suppress_logs and original_stdout is not None and original_stderr is not None:
            # Restore stdout/stderr
            # Since both point to the same devnull_fd, we only need to close once
            try:
                if devnull_fd is not None and hasattr(devnull_fd, "close"):
                    devnull_fd.close()
            except Exception:
                pass  # Ignore errors during cleanup
            sys.stdout = original_stdout
            sys.stderr = original_stderr
