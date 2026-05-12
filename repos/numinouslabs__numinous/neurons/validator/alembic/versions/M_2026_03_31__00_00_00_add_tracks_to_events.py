"""Add tracks column to events table

Revision ID: 3c5f7a9b2d4e
Revises: 2b4e6f8a1c3d
Create Date: 2026-03-31 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c5f7a9b2d4e"
down_revision: Union[str, None] = "2b4e6f8a1c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN tracks TEXT NOT NULL DEFAULT '[\"MAIN\"]'")


def downgrade() -> None:
    pass
