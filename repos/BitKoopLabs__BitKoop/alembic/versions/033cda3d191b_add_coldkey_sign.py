"""add_coldkey_sign

Revision ID: 033cda3d191b
Revises: add_site_slots
Create Date: 2025-09-03 12:48:07.428355

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "033cda3d191b"
down_revision: Union[str, Sequence[str], None] = "add_site_slots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "coupons", sa.Column("miner_coldkey", sa.String(), nullable=True)
    )
    op.add_column(
        "coupons",
        sa.Column("use_coldkey_for_signature", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("coupons", "use_coldkey_for_signature")
    op.drop_column("coupons", "miner_coldkey")
