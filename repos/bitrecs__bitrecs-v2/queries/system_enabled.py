from utils.database import db_operation

@db_operation
async def get_system_enabled(conn) -> bool:
    result = await conn.fetchval("SELECT enabled FROM system_enabled LIMIT 1")    
    is_enabled = bool(result) if result is not None else False    
    return is_enabled