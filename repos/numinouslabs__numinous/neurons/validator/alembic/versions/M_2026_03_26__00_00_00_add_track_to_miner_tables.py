"""Add track to miner tables

Revision ID: 8a1c3f5e7d9b
Revises: 0580d6156c28
Create Date: 2026-03-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a1c3f5e7d9b"
down_revision: Union[str, None] = "0580d6156c28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE miner_agents ADD COLUMN track TEXT NOT NULL DEFAULT 'MAIN'")
    op.execute(
        """
            CREATE UNIQUE INDEX idx_miner_agents_track_unique
            ON miner_agents(miner_uid, miner_hotkey, track, version_number)
        """
    )

    op.execute("ALTER TABLE agent_runs ADD COLUMN track TEXT NOT NULL DEFAULT 'MAIN'")

    op.execute("ALTER TABLE predictions ADD COLUMN track TEXT NOT NULL DEFAULT 'MAIN'")
    op.execute(
        """
            CREATE UNIQUE INDEX idx_predictions_track_unique
            ON predictions(unique_event_id, miner_uid, miner_hotkey, track, interval_start_minutes)
        """
    )

    op.execute("ALTER TABLE scores ADD COLUMN track TEXT NOT NULL DEFAULT 'MAIN'")
    op.execute(
        """
            CREATE UNIQUE INDEX idx_scores_track_unique
            ON scores(event_id, miner_uid, miner_hotkey, track)
        """
    )


def downgrade() -> None:
    pass
