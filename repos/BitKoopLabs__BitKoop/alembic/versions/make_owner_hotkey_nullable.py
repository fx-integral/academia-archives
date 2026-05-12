"""make owner_hotkey nullable in coupon_ownerships

Revision ID: f2e3d4c5b6a7
Revises: e1b2c3d4a5f6
Create Date: 2025-01-27 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2e3d4c5b6a7"
down_revision: Union[str, Sequence[str], None] = "e1b2c3d4a5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Make owner_hotkey nullable in coupon_ownerships table
    # Use batch_alter_table for SQLite compatibility (recreates table under the hood)
    with op.batch_alter_table("coupon_ownerships") as batch_op:
        batch_op.alter_column(
            "owner_hotkey",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Make owner_hotkey non-nullable again
    # Use batch_alter_table for SQLite compatibility (recreates table under the hood)
    with op.batch_alter_table("coupon_ownerships") as batch_op:
        batch_op.alter_column(
            "owner_hotkey",
            existing_type=sa.String(),
            nullable=False,
        )
