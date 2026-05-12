import pytest
import asyncio
import time
from utils.debug_lock import DebugLockManager, DebugLock, get_debug_lock_info

@pytest.mark.asyncio
async def test_debug_lock_manager_add_waiting():
    manager = DebugLockManager(max_entries=10)
    entry_id = "test_id"
    label = "test_label"
    waiting_at = time.monotonic()
    
    await manager.add_waiting(entry_id, label, waiting_at)
    
    assert entry_id in manager.waiting
    assert manager.waiting[entry_id]["label"] == label
    assert manager.waiting[entry_id]["waiting_at"] == waiting_at

@pytest.mark.asyncio
async def test_debug_lock_manager_move_to_locked():
    manager = DebugLockManager()
    entry_id = "test_id"
    label = "test_label"
    waiting_at = time.monotonic()
    acquired_at = time.monotonic()
    
    await manager.add_waiting(entry_id, label, waiting_at)
    await manager.move_to_locked(entry_id, acquired_at)
    
    assert entry_id not in manager.waiting
    assert entry_id in manager.locked
    assert manager.locked[entry_id]["label"] == label
    assert manager.locked[entry_id]["acquired_at"] == acquired_at

@pytest.mark.asyncio
async def test_debug_lock_manager_remove_locked():
    manager = DebugLockManager(slow_threshold=0.1)  # Low threshold for testing
    entry_id = "test_id"
    label = "test_label"
    waiting_at = time.monotonic()
    acquired_at = time.monotonic()
    released_at = acquired_at + 0.2  # Exceed threshold
    
    await manager.add_waiting(entry_id, label, waiting_at)
    await manager.move_to_locked(entry_id, acquired_at)
    await manager.remove_locked(entry_id, released_at)
    
    assert entry_id not in manager.locked
    assert len(manager.slow) == 1
    assert manager.slow[0]["label"] == label

@pytest.mark.asyncio
async def test_debug_lock_manager_max_entries():
    manager = DebugLockManager(max_entries=2)
    
    await manager.add_waiting("id1", "label1", time.monotonic())
    await manager.add_waiting("id2", "label2", time.monotonic())
    await manager.add_waiting("id3", "label3", time.monotonic())  # Should not add
    
    assert len(manager.waiting) == 2
    assert "id3" not in manager.waiting

def test_debug_lock_manager_get_info():
    manager = DebugLockManager()
    # Add some mock data
    manager.waiting = {"id1": {"label": "wait", "waiting_at": time.time() - 1}}
    manager.locked = {"id2": {"label": "lock", "acquired_at": time.time() - 2}}
    manager.slow = [{"label": "slow", "acquired_at": time.time() - 5, "released_at": time.time()}]
    
    info = manager.get_info()
    assert "waiting" in info
    assert "locked" in info
    assert "slow" in info
    assert len(info["waiting"]) == 1
    assert len(info["locked"]) == 1
    assert len(info["slow"]) == 1


@pytest.mark.asyncio
async def test_debug_lock_timeout():
    lock = asyncio.Lock()
    debug_lock = DebugLock(lock, "test", timeout=0.1, enabled=True)
    
    # Acquire lock to cause timeout
    await lock.acquire()
    
    with pytest.raises(asyncio.TimeoutError):
        async with debug_lock:
            pass
    
    lock.release()  # Cleanup

def test_get_debug_lock_info():
    # Test the global function
    info = get_debug_lock_info()
    assert isinstance(info, dict)
    assert "waiting" in info
    assert "locked" in info
    assert "slow" in info