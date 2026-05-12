import time
import asyncio
import uuid
import utils.logger as logger
from collections import deque

class DebugLockManager:
    """Encapsulated manager for debug lock data to improve security and prevent global access."""
    def __init__(self, max_entries: int = 10_000, slow_threshold: float = 5.0):
        self.max_entries = max_entries
        self.slow_threshold = slow_threshold
        self.waiting = {}
        self.locked = {}
        self.slow = deque(maxlen=max_entries)  # Deque with max size to prevent leaks
        self.lock = asyncio.Lock()

    async def add_waiting(self, entry_id: str, label: str, waiting_at: float):
        async with self.lock:
            if len(self.waiting) < self.max_entries:
                self.waiting[entry_id] = {"label": label, "waiting_at": waiting_at}

    async def move_to_locked(self, entry_id: str, acquired_at: float):
        async with self.lock:
            if entry_id in self.waiting:
                entry = self.waiting.pop(entry_id)
                entry["acquired_at"] = acquired_at
                self.locked[entry_id] = entry

    async def remove_locked(self, entry_id: str, released_at: float):
        async with self.lock:
            if entry_id in self.locked:
                entry = self.locked.pop(entry_id)
                entry["released_at"] = released_at
                elapsed = released_at - entry["acquired_at"]
                if elapsed > self.slow_threshold:
                    self.slow.append(entry)

    def get_info(self):
        now = time.time()
        waiting_info = [f"{entry['label']} - {now - entry['waiting_at']:.2f} s" for entry in self.waiting.values()]
        locked_info = [f"{entry['label']} - {now - entry['acquired_at']:.2f} s" for entry in self.locked.values()]
        slow_info = [f"{entry['label']} - {entry['released_at'] - entry['acquired_at']:.2f} s" for entry in self.slow]
        return {"waiting": waiting_info, "locked": locked_info, "slow": slow_info}

# Global instance for simplicity, but can be injected or made singleton
DEBUG_MANAGER = DebugLockManager()

class DebugLock:
    def __init__(self, lock: asyncio.Lock, label: str, timeout: float = None, enabled: bool = True):
        self.lock = lock
        self.label = label
        self.timeout = timeout
        self.enabled = enabled

    async def __aenter__(self):
        if not self.enabled:
            await self.lock.acquire()
            return self

        self.entry_id = str(uuid.uuid4())
        self.waiting_at = time.monotonic()
        logger.debug(f"[DebugLock] {self.label}: Trying to acquire lock...")
        await DEBUG_MANAGER.add_waiting(self.entry_id, self.label, self.waiting_at)

        try:
            if self.timeout is not None:
                await asyncio.wait_for(self.lock.acquire(), timeout=self.timeout)
            else:
                await self.lock.acquire()
        except asyncio.TimeoutError:
            await DEBUG_MANAGER.lock.acquire()  # Ensure cleanup
            if self.entry_id in DEBUG_MANAGER.waiting:
                del DEBUG_MANAGER.waiting[self.entry_id]
            DEBUG_MANAGER.lock.release()
            logger.error(f"[DebugLock] {self.label}: Failed to acquire lock within {self.timeout} seconds")
            raise

        self.acquired_at = time.monotonic()
        await DEBUG_MANAGER.move_to_locked(self.entry_id, self.acquired_at)
        elapsed = self.acquired_at - self.waiting_at
        logger.debug(f"[DebugLock] {self.label}: Lock acquired after waiting for {elapsed:.2f} seconds")
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.lock.release()
        if not self.enabled:
            return

        self.released_at = time.monotonic()
        elapsed = self.released_at - self.acquired_at
        await DEBUG_MANAGER.remove_locked(self.entry_id, self.released_at)
        logger.debug(f"[DebugLock] {self.label}: Lock released after being locked for {elapsed:.2f} seconds")

def get_debug_lock_info():
    return DEBUG_MANAGER.get_info()