import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    db_path = os.getenv("VALIDATOR_DB_PATH")
    if db_path:
        db_path = Path(db_path)
        if not db_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            db_path = project_root / db_path
        return db_path
    else:
        home_dir = Path.home()
        wahoo_dir = home_dir / ".wahoo"
        wahoo_dir.mkdir(parents=True, exist_ok=True)
        return wahoo_dir / "validator.db"


def run_alembic_migrations(db_path: Optional[Path] = None) -> None:
    """Apply schema migrations directly via SQLite (fast, no alembic runtime)."""
    if db_path is None:
        db_path = get_db_path()

    db_path = Path(db_path)
    if not db_path.exists():
        logger.debug("Database does not exist yet, skipping migrations")
        return

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        if "performance_snapshots" not in tables:
            conn.close()
            return

        cursor.execute("PRAGMA table_info(performance_snapshots)")
        columns = {row[1] for row in cursor.fetchall()}

        applied = []

        if "weighted_volume" not in columns:
            cursor.execute(
                "ALTER TABLE performance_snapshots ADD COLUMN weighted_volume REAL"
            )
            applied.append("weighted_volume")

        if "profit" not in columns:
            cursor.execute(
                "ALTER TABLE performance_snapshots ADD COLUMN profit REAL"
            )
            applied.append("profit")

        # Track migration state in alembic_version for CLI compatibility
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        cursor.execute("DELETE FROM alembic_version")
        cursor.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            ("002_add_profit",),
        )

        conn.commit()
        conn.close()

        if applied:
            logger.info(f"Applied schema migrations: added columns {applied}")
        else:
            logger.info("Database schema is up to date")

    except Exception as e:
        logger.error(f"Schema migration failed: {e}")


def get_or_create_database(db_path: Optional[Path] = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = get_db_path()

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    if not tables:
        schema_file = Path(__file__).parent / "schema.sql"
        if schema_file.exists():
            with open(schema_file, "r") as f:
                schema_sql = f.read()
            conn.executescript(schema_sql)
            conn.commit()

    return conn


def check_database_exists(db_path: Optional[Path] = None) -> bool:
    if db_path is None:
        db_path = get_db_path()

    db_path = Path(db_path)

    if not db_path.exists():
        return False

    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        conn.close()

        if db_path.stat().st_size > 0:
            try:
                with open(db_path, "rb") as f:
                    header = f.read(16)
                    if len(header) >= 16 and not header.startswith(
                        b"SQLite format 3\x00"
                    ):
                        return False
            except (IOError, OSError):
                pass
        return True
    except sqlite3.Error:
        return False
