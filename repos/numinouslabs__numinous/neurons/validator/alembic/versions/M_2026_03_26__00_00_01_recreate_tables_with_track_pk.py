"""Recreate tables with track in primary key

The previous migration added the track column and new unique indexes, but
SQLite cannot alter primary keys without table recreation.

Revision ID: 2b4e6f8a1c3d
Revises: 8a1c3f5e7d9b
Create Date: 2026-03-26 00:00:01.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b4e6f8a1c3d"
down_revision: Union[str, None] = "8a1c3f5e7d9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _recreate_table(
    table_name: str,
    create_sql: str,
    columns: list[str],
    indexes: list[str] | None = None,
) -> None:
    new_table = f"_{table_name}_new"
    columns_csv = ", ".join(columns)

    # Create new table with updated schema
    op.execute(create_sql.replace(f"CREATE TABLE {table_name}", f"CREATE TABLE {new_table}", 1))

    # Copy all data
    op.execute(f"INSERT INTO {new_table} ({columns_csv}) SELECT {columns_csv} FROM {table_name}")

    # Drop old table + rename new (FK references by name stay valid)
    op.execute(f"DROP TABLE {table_name}")
    op.execute(f"ALTER TABLE {new_table} RENAME TO {table_name}")

    # Recreate indexes
    for index_sql in indexes or []:
        op.execute(index_sql)


def upgrade() -> None:
    _recreate_table(
        table_name="miner_agents",
        create_sql="""
            CREATE TABLE miner_agents (
                version_id              TEXT PRIMARY KEY,
                miner_uid               INTEGER NOT NULL,
                miner_hotkey            TEXT NOT NULL,
                track                   TEXT NOT NULL DEFAULT 'MAIN',
                agent_name              TEXT NOT NULL,
                version_number          INTEGER NOT NULL,
                file_path               TEXT NOT NULL,
                pulled_at               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at              DATETIME NOT NULL,
                UNIQUE(miner_uid, miner_hotkey, track, version_number)
            )
        """,
        columns=[
            "version_id",
            "miner_uid",
            "miner_hotkey",
            "track",
            "agent_name",
            "version_number",
            "file_path",
            "pulled_at",
            "created_at",
        ],
        indexes=[
            "CREATE INDEX idx_miner_agents_lookup ON miner_agents(miner_uid, miner_hotkey)",
            "CREATE INDEX idx_miner_agents_pulled ON miner_agents(pulled_at)",
        ],
    )

    _recreate_table(
        table_name="predictions",
        create_sql="""
            CREATE TABLE predictions (
                unique_event_id            TEXT NOT NULL,
                miner_uid                  INTEGER NOT NULL,
                miner_hotkey               TEXT NOT NULL,
                track                      TEXT NOT NULL DEFAULT 'MAIN',
                latest_prediction          REAL NOT NULL,
                interval_start_minutes     INTEGER NOT NULL,
                interval_agg_prediction    REAL NOT NULL,
                interval_count             INTEGER NOT NULL,
                submitted                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                exported                   BOOLEAN NOT NULL DEFAULT FALSE,
                run_id                     TEXT,
                version_id                 TEXT,
                PRIMARY KEY (unique_event_id, miner_uid, miner_hotkey, track, interval_start_minutes),
                FOREIGN KEY (unique_event_id)
                    REFERENCES events(unique_event_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            )
        """,
        columns=[
            "unique_event_id",
            "miner_uid",
            "miner_hotkey",
            "track",
            "latest_prediction",
            "interval_start_minutes",
            "interval_agg_prediction",
            "interval_count",
            "submitted",
            "updated_at",
            "exported",
            "run_id",
            "version_id",
        ],
        indexes=[
            "CREATE INDEX idx_predictions_exported ON predictions(exported)",
            "CREATE INDEX idx_predictions_version_id ON predictions(version_id)",
        ],
    )

    _recreate_table(
        table_name="scores",
        create_sql="""
            CREATE TABLE scores (
                event_id         TEXT NOT NULL,
                miner_uid        INTEGER NOT NULL,
                miner_hotkey     TEXT NOT NULL,
                track            TEXT NOT NULL DEFAULT 'MAIN',
                prediction       REAL NOT NULL,
                event_score      REAL NOT NULL,
                created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                spec_version     INTEGER NOT NULL,
                exported         BOOLEAN NOT NULL DEFAULT false,
                PRIMARY KEY (event_id, miner_uid, miner_hotkey, track)
            )
        """,
        columns=[
            "event_id",
            "miner_uid",
            "miner_hotkey",
            "track",
            "prediction",
            "event_score",
            "created_at",
            "spec_version",
            "exported",
        ],
    )


def downgrade() -> None:
    pass
