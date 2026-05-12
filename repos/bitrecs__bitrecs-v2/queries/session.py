import hashlib
from typing import Optional
from utils.database import db_operation, DatabaseConnection

@db_operation
async def insert_validator_session(conn: DatabaseConnection, session, name, hotkey, ip, commit_hash) -> Optional[int]:    
    try:
        sha_session = hashlib.sha256(str(session).encode()).hexdigest()
        result = await conn.fetchval("""
        INSERT INTO sessions (
            session_id,
            node_name,
            node_hotkey,
            ip_address,
            commit_hash     
        ) VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """, sha_session, name, hotkey, ip, commit_hash)
        return result
    except Exception as e:
        print(f"Error inserting validator session: {e}")
        return -1
