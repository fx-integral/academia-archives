from utils.database import db_operation, DatabaseConnection

@db_operation
async def get_current_rate(conn: DatabaseConnection) -> int:
    result = await conn.fetchrow(
        "SELECT COUNT(*) FROM agents WHERE created_at > NOW() - INTERVAL '1 hour'"
    )
    return result[0] if result else 0
