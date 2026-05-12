from typing import List
from utils.database import db_operation, DatabaseConnection

@db_operation
async def load_keys(conn: DatabaseConnection) -> List[str]:
    result = await conn.fetch(
        """
        SELECT DISTINCT auth_token FROM validators WHERE Enabled = true
        """
    )
    return [row["auth_token"].strip() for row in result]

