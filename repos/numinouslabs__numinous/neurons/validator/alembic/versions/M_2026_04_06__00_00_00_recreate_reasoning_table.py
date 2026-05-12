"""Recreate reasoning table keyed by run_id

Revision ID: 4d6e8f0a2b5c
Revises: 3c5f7a9b2d4e
Create Date: 2026-04-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4d6e8f0a2b5c"
down_revision: Union[str, None] = "3c5f7a9b2d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reasoning")

    op.execute(
        """
            CREATE TABLE IF NOT EXISTS reasoning (
                run_id TEXT NOT NULL PRIMARY KEY,
                reasoning TEXT NOT NULL,
                exported BOOLEAN NOT NULL DEFAULT false,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """
    )
