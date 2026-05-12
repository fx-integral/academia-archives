"""Add events title

Revision ID: 7ffd8ddf05a2
Revises: 09014f49f29f
Create Date: 2025-11-25 05:21:38.488409

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7ffd8ddf05a2"
down_revision: Union[str, None] = "09014f49f29f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
            ALTER TABLE events ADD COLUMN title TEXT
        """
    )
