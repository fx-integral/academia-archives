"""Add profit column to performance_snapshots

Revision ID: 002_add_profit
Revises: 001_add_weighted_volume
Create Date: 2026-02-20

This migration adds the 'profit' column to the performance_snapshots table
to support profit-based scoring instead of weighted_volume-based scoring.
"""

from alembic import op
import sqlalchemy as sa


revision = "002_add_profit"
down_revision = "001_add_weighted_volume"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "performance_snapshots" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("performance_snapshots")}

    if "profit" not in columns:
        op.add_column(
            "performance_snapshots",
            sa.Column("profit", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("performance_snapshots", "profit")
