"""Add weighted_volume column to performance_snapshots

Revision ID: 001_add_weighted_volume
Revises:
Create Date: 2026-02-02
"""

from alembic import op
import sqlalchemy as sa


revision = "001_add_weighted_volume"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "performance_snapshots" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("performance_snapshots")}

    if "weighted_volume" not in columns:
        op.add_column(
            "performance_snapshots",
            sa.Column("weighted_volume", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("performance_snapshots", "weighted_volume")
