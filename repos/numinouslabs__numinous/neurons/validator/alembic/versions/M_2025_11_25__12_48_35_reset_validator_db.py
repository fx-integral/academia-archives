"""Reset validator db - flush all data

Revision ID: d679a148c4f2
Revises: 7ffd8ddf05a2
Create Date: 2025-11-25 12:48:35.825185

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import Inspector, text

# revision identifiers, used by Alembic.
revision: str = "d679a148c4f2"
down_revision: Union[str, None] = "7ffd8ddf05a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)

    table_names = [table for table in inspector.get_table_names() if table != "alembic_version"]

    if conn.dialect.name == "sqlite":
        op.execute(text("PRAGMA foreign_keys=OFF"))

    for table in table_names:
        print(f"Flushing data from table: {table}")
        op.execute(text(f"DELETE FROM {table}"))

    if conn.dialect.name == "sqlite":
        op.execute(text("PRAGMA foreign_keys=ON"))
