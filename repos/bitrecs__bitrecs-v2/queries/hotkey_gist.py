from uuid import UUID
from typing import Optional
from models.miner_submission import GistInfo
from utils.database import db_operation, DatabaseConnection

@db_operation
async def log_hotkey_gist(conn: DatabaseConnection, hotkey: str, gist: str, block: int, artifact_id: UUID, uid: int, github_account: str) -> None:
    result = await conn.fetchrow(
        """
        INSERT INTO hotkey_gist (miner_hotkey, gist, block, uid, artifact_id, github_account) VALUES ($1, $2, $3, $4, $5, $6)
        """,
        hotkey, gist, block, uid, artifact_id, github_account
    )


@db_operation
async def get_hotkey_from_gist(conn: DatabaseConnection, gist: str) -> Optional[str]:
    hotkey = await conn.fetchrow(
        """
        SELECT miner_hotkey FROM hotkey_gist WHERE gist = $1
        """,
        gist      
    )
    if not hotkey:
        return None
    return hotkey[0]



@db_operation
async def get_miner_first_blocks(conn: DatabaseConnection) -> dict[str, int]:
    rows = await conn.fetch(
        """
        SELECT miner_hotkey, MIN(block) as first_block 
        FROM hotkey_gist 
        WHERE block != 0
        GROUP BY miner_hotkey
        """
    )
    return {row['miner_hotkey']: row['first_block'] for row in rows}


@db_operation
async def get_gist_info_from_agent_id(conn: DatabaseConnection, agent_id: UUID) -> Optional[GistInfo]:
    row = await conn.fetchrow(
        """
        SELECT created_at, gist, github_account, miner_hotkey, block 
        FROM hotkey_gist 
        WHERE artifact_id = $1
        """,
        agent_id      
    )   
    if not row:
        return None
    
    created_at = row['created_at'].isoformat() if row['created_at'] is not None else ""
    gist_id = row['gist'] or ""
    github_account = row['github_account'] or ""
    hotkey = row['miner_hotkey'] or ""
    block = row['block']
    return GistInfo(
        created_at=created_at,
        gist_id=gist_id,
        github_account=github_account,
        hotkey=hotkey,
        block=block
    )
