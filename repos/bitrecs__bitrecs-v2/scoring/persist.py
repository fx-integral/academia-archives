import time
import logging
import sqlite3
import pandas as pd
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from threading import Lock
from scoring.types import MinerUID


logger = logging.getLogger(__name__)


class ScorePersister:
    """
    SQLite-backed persistence for miner scores.
 
    """

    def __init__(self, base_path: str = "data/weights", filename: str = "scores.db"):
        self.save_dir = Path(base_path)
        self.file_path = self.save_dir / filename
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS miner_scores (
                    run_id TEXT NOT NULL,
                    uid INTEGER NOT NULL, 
                    hotkey TEXT NOT NULL,                    
                    task_name TEXT,
                    score REAL NOT NULL,
                    success BOOLEAN,                    
                    duration REAL,
                    created_at TEXT,
                    evaluation_set_id INTEGER,
                    sample_size INTEGER,
                    validator_hotkey TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_uid ON miner_scores(uid)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_run ON miner_scores(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_hotkey ON miner_scores(hotkey)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_task ON miner_scores(task_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_evaluation_set_id ON miner_scores(evaluation_set_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_sample_size ON miner_scores(sample_size)")
            
            conn.commit()
      

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.file_path)
        try:
            yield conn
        finally:
            conn.close() 
   

    def save_result(
        self,
        uid: MinerUID,
        hotkey: str,
        score: float,
        run_id: str,
        task_name: str | None = None,
        success: bool | None = None,
        duration: float | None = None,
        created_at: str | None = None,
        evaluation_set_id: Optional[int] = None,
        sample_size: Optional[int] = None,
    ) -> bool:
        """Insert a single scored result with metadata."""

        try:        

            created_at = created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            row = (run_id, int(uid), hotkey, task_name, score, success, duration, created_at, evaluation_set_id, sample_size)

            with self._lock, self._connect() as conn:
                conn.execute("""
                    INSERT INTO miner_scores (run_id, uid, hotkey, task_name, score, success, duration, created_at, evaluation_set_id, sample_size)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, row)
                conn.commit()
                logger.info(f"Saved result for uid {uid} to {self.file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save result for uid {uid}: {e}")
            return False

    def update_schema(self, table_name: str, columns: dict[str, str]):
        """
        Dynamically add missing columns to a table before saving results (synchronous).
        
        Args:
            table_name: Name of the table to update.
            columns: Dict of {column_name: sql_type}, e.g., {'evaluation_set_id': 'INTEGER'}
        """
        with self._lock, self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns_info = cursor.fetchall()
            existing_columns = [col[1] for col in columns_info]
            
            for col_name, col_type in columns.items():
                if col_name not in existing_columns:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                    logger.info(f"Added column '{col_name}' of type '{col_type}' to table '{table_name}'")
            conn.commit()

    def load_scores(self, evaluation_set_id: int) -> pd.DataFrame:
        """Load all scores for a given evaluation set ID."""
        with self._connect() as conn:
            df = pd.read_sql_query(
                """SELECT * FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY hotkey, task_name ORDER BY score DESC, created_at DESC) AS rn
                    FROM miner_scores 
                    WHERE evaluation_set_id = ?
                ) WHERE rn = 1""",
                conn,
                params=(evaluation_set_id,)
            )
        return df
