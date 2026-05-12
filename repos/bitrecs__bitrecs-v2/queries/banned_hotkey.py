from typing import Optional
from models.banned_hotkey import BannedHotkey
from utils.database import db_operation, DatabaseConnection

@db_operation
async def is_hotkey_used(conn: DatabaseConnection, hotkey: str) -> bool:
    result = await conn.fetchrow(
        """
        SELECT COUNT(*) FROM agents WHERE miner_hotkey = $1
        """,
        hotkey
    )
    return result[0] > 0


@db_operation
async def get_banned_hotkey(conn: DatabaseConnection, miner_hotkey: str) -> Optional[BannedHotkey]:
    banned_hotkey = await conn.fetchrow(
        """
        SELECT * FROM banned_hotkeys WHERE miner_hotkey = $1
        """,
        miner_hotkey
    )

    if not banned_hotkey:
        return None

    return BannedHotkey(**banned_hotkey)


@db_operation
async def add_banned_hotkey(conn: DatabaseConnection, miner_hotkey: str, banned_reason: str) -> bool:
    existing = await get_banned_hotkey(miner_hotkey)
    if existing:
        return True # Already banned
    
    banned_hotkey = await conn.fetchrow(
        """
        INSERT INTO banned_hotkeys (miner_hotkey, banned_reason)
        VALUES ($1, $2)
        RETURNING *
        """,
        miner_hotkey,
        banned_reason
    )

    return banned_hotkey is not None
