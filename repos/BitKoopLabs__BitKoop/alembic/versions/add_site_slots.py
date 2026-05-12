"""add site slots

Revision ID: add_site_slots
Revises: 8698bb73f782
Create Date: 2024-01-01 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_site_slots"
down_revision = "8698bb73f782"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add slot columns to sites table
    # total_coupon_slots: configured by supervisor API
    # available_slots: calculated locally based on current coupon statuses
    op.add_column(
        "sites",
        sa.Column(
            "total_coupon_slots",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
    )
    op.add_column(
        "sites",
        sa.Column(
            "available_slots",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
    )


def downgrade() -> None:
    # Remove slot columns from sites table
    op.drop_column("sites", "available_slots")
    op.drop_column("sites", "total_coupon_slots")
