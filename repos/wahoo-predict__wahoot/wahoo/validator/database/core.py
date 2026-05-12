import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..api.client import ValidatorDBInterface
from .validator_db import get_or_create_database

logger = logging.getLogger(__name__)

DEFAULT_SNAPSHOT_RETENTION_DAYS = int(
    os.getenv("VALIDATOR_SNAPSHOT_RETENTION_DAYS", "3")
)
DEFAULT_SCORING_RETENTION_DAYS = int(os.getenv("VALIDATOR_SCORING_RETENTION_DAYS", "7"))


class ValidatorDB(ValidatorDBInterface):
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        get_or_create_database(self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        return get_or_create_database(self.db_path)

    def cache_validation_data(self, hotkey: str, data_dict: Dict[str, Any]) -> None:
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            perf = data_dict.get("performance", {})

            timestamp = datetime.utcnow().isoformat() + "Z"

            cursor.execute(
                """
                INSERT INTO performance_snapshots (
                    hotkey, timestamp,
                    total_volume_usd, weighted_volume, profit, trade_count,
                    realized_profit_usd, unrealized_profit_usd, win_rate,
                    total_fees_paid_usd, open_positions_count,
                    referral_count, referral_volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hotkey,
                    timestamp,
                    perf.get("total_volume_usd"),
                    perf.get("weighted_volume"),
                    perf.get("profit"),
                    perf.get("trade_count"),
                    perf.get("realized_profit_usd"),
                    perf.get("unrealized_profit_usd"),
                    perf.get("win_rate"),
                    perf.get("total_fees_paid_usd"),
                    perf.get("open_positions_count"),
                    perf.get("referral_count"),
                    perf.get("referral_volume_usd"),
                ),
            )

            cursor.execute(
                """
                INSERT INTO miners (hotkey, last_seen_ts)
                VALUES (?, ?)
                ON CONFLICT(hotkey) DO UPDATE SET last_seen_ts = excluded.last_seen_ts
                """,
                (hotkey, timestamp),
            )

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to cache validation data for {hotkey}: {e}")

    def get_cached_validation_data(
        self, hotkeys: Sequence[str], max_age_days: int = 7
    ) -> List[Dict[str, Any]]:
        if not hotkeys:
            return []

        try:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cutoff_date = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()

            placeholders = ",".join("?" for _ in hotkeys)
            query = f"""
                SELECT * FROM performance_snapshots
                WHERE hotkey IN ({placeholders})
                AND timestamp > ?
                ORDER BY timestamp DESC
            """

            query = f"""
                SELECT * FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (PARTITION BY hotkey ORDER BY timestamp DESC) as rn
                    FROM performance_snapshots
                    WHERE hotkey IN ({placeholders})
                    AND timestamp > ?
                ) WHERE rn = 1
            """

            params = list(hotkeys) + [cutoff_date]
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            results = []
            for row in rows:
                data = dict(row)
                perf = {
                    "total_volume_usd": data["total_volume_usd"],
                    "weighted_volume": data["weighted_volume"],
                    "profit": data.get("profit"),
                    "trade_count": data["trade_count"],
                    "realized_profit_usd": data["realized_profit_usd"],
                    "unrealized_profit_usd": data["unrealized_profit_usd"],
                    "win_rate": data["win_rate"],
                    "total_fees_paid_usd": data["total_fees_paid_usd"],
                    "open_positions_count": data["open_positions_count"],
                    "referral_count": data["referral_count"],
                    "referral_volume_usd": data["referral_volume"],
                }

                record = {
                    "hotkey": data["hotkey"],
                    "performance": perf,
                }
                results.append(record)

            return results

        except Exception as e:
            logger.error(f"Failed to retrieve cached data: {e}")
            return []

    def delete_cached_validation_data(self, hotkeys: Sequence[str]) -> None:
        if not hotkeys:
            return

        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in hotkeys)
            cursor.execute(
                f"DELETE FROM performance_snapshots WHERE hotkey IN ({placeholders})",
                list(hotkeys),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to delete cached data: {e}")

    def cleanup_old_cache(
        self,
        snapshot_retention_days: Optional[int] = None,
        scoring_retention_days: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Clean up old database entries automatically.

        Args:
            snapshot_retention_days: Days to keep performance_snapshots (default: 3)
            scoring_retention_days: Days to keep scoring_runs (default: 7)

        Returns:
            Dict with 'snapshots_deleted' and 'scoring_runs_deleted' counts
        """
        if snapshot_retention_days is None:
            snapshot_retention_days = DEFAULT_SNAPSHOT_RETENTION_DAYS
        if scoring_retention_days is None:
            scoring_retention_days = DEFAULT_SCORING_RETENTION_DAYS

        result = {"snapshots_deleted": 0, "scoring_runs_deleted": 0}

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            snapshot_cutoff = (
                datetime.utcnow() - timedelta(days=snapshot_retention_days)
            ).isoformat()
            cursor.execute(
                "DELETE FROM performance_snapshots WHERE timestamp < ?",
                (snapshot_cutoff,),
            )
            result["snapshots_deleted"] = cursor.rowcount

            scoring_cutoff = (
                datetime.utcnow() - timedelta(days=scoring_retention_days)
            ).isoformat()
            cursor.execute(
                "DELETE FROM scoring_runs WHERE ts < ?",
                (scoring_cutoff,),
            )
            result["scoring_runs_deleted"] = cursor.rowcount

            conn.commit()

            if result["snapshots_deleted"] > 0 or result["scoring_runs_deleted"] > 0:
                conn.execute("VACUUM")
                conn.commit()

            conn.close()

            return result
        except Exception as e:
            logger.error(f"Failed to cleanup database: {e}")
            return result

    def add_scoring_run(
        self, scores: Dict[str, float], reason: str = "ema_update"
    ) -> None:
        if not scores:
            return

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            timestamp = datetime.utcnow().isoformat() + "Z"

            data = [
                (timestamp, hotkey, score, reason) for hotkey, score in scores.items()
            ]

            cursor.executemany(
                "INSERT INTO scoring_runs (ts, hotkey, score, reason) VALUES (?, ?, ?, ?)",
                data,
            )

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save scoring run: {e}")

    def get_latest_scores(self) -> Dict[str, float]:
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            query = """
                SELECT hotkey, score
                FROM (
                    SELECT hotkey, score,
                           ROW_NUMBER() OVER (PARTITION BY hotkey ORDER BY ts DESC) as rn
                    FROM scoring_runs
                )
                WHERE rn = 1
            """

            cursor.execute(query)
            rows = cursor.fetchall()
            conn.close()

            return {row[0]: row[1] for row in rows}
        except Exception as e:
            logger.error(f"Failed to retrieve latest scores: {e}")
            return {}

    def sync_miner_metadata(
        self, hotkey_to_uid: Dict[str, int], hotkey_to_axon_ip: Optional[Dict[str, str]] = None
    ) -> None:
        if not hotkey_to_uid:
            return
        
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            for hotkey, uid in hotkey_to_uid.items():
                if hotkey_to_axon_ip and hotkey in hotkey_to_axon_ip:
                    axon_ip = hotkey_to_axon_ip[hotkey]
                    cursor.execute(
                        """
                        UPDATE miners 
                        SET uid = ?, axon_ip = ?
                        WHERE hotkey = ?
                        """,
                        (uid, axon_ip, hotkey),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE miners 
                        SET uid = ?
                        WHERE hotkey = ?
                        """,
                        (uid, hotkey),
                    )
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to sync miner metadata: {e}")

    def remove_unregistered_miners(self, registered_hotkeys: Sequence[str]) -> int:
        if not registered_hotkeys:
            logger.warning("No registered hotkeys provided, skipping removal")
            return 0

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # Get all hotkeys currently in the database
            cursor.execute("SELECT hotkey FROM miners")
            db_hotkeys = {row[0] for row in cursor.fetchall()}

            # Find hotkeys that are in DB but not in registered list
            registered_set = set(registered_hotkeys)
            unregistered_hotkeys = db_hotkeys - registered_set

            if not unregistered_hotkeys:
                conn.close()
                return 0

            # Delete from related tables (order matters due to foreign key constraints)
            # First delete from performance_snapshots (has foreign key to miners)
            placeholders = ",".join("?" for _ in unregistered_hotkeys)
            cursor.execute(
                f"DELETE FROM performance_snapshots WHERE hotkey IN ({placeholders})",
                list(unregistered_hotkeys),
            )
            snapshots_deleted = cursor.rowcount

            # Delete from scoring_runs
            cursor.execute(
                f"DELETE FROM scoring_runs WHERE hotkey IN ({placeholders})",
                list(unregistered_hotkeys),
            )
            scoring_runs_deleted = cursor.rowcount

            cursor.execute(
                f"DELETE FROM user_hotkey_bindings WHERE hotkey IN ({placeholders})",
                list(unregistered_hotkeys),
            )
            bindings_deleted = cursor.rowcount

            # Finally delete from miners table
            cursor.execute(
                f"DELETE FROM miners WHERE hotkey IN ({placeholders})",
                list(unregistered_hotkeys),
            )
            miners_deleted = cursor.rowcount

            conn.commit()
            conn.close()

            logger.info(
                f"Removed {miners_deleted} unregistered miners from database: "
                f"{snapshots_deleted} performance snapshots, "
                f"{scoring_runs_deleted} scoring runs deleted"
            )

            return miners_deleted
        except Exception as e:
            logger.error(f"Failed to remove unregistered miners: {e}")
            return 0

    def _ensure_bindings_table(self, conn: sqlite3.Connection) -> None:
        """Ensure the user_hotkey_bindings table exists (for schema migration)."""
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_hotkey_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                hotkey TEXT NOT NULL UNIQUE,
                first_seen_at TEXT NOT NULL,
                last_updated_at TEXT NOT NULL,
                previous_user_id TEXT,
                FOREIGN KEY(hotkey) REFERENCES miners(hotkey)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_hotkey_bindings_user_id
            ON user_hotkey_bindings(user_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_hotkey_bindings_hotkey
            ON user_hotkey_bindings(hotkey)
        """)
        conn.commit()

    def get_binding_for_hotkey(self, hotkey: str) -> Optional[Dict[str, Any]]:
        try:
            conn = self._get_conn()
            self._ensure_bindings_table(conn)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT * FROM user_hotkey_bindings WHERE hotkey = ?",
                (hotkey,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"Failed to get binding for hotkey {hotkey}: {e}")
            return None

    def update_user_hotkey_binding(
        self, 
        user_id: Optional[str], 
        hotkey: str
    ) -> Tuple[Optional[str], bool]:
        try:
            conn = self._get_conn()
            self._ensure_bindings_table(conn)
            cursor = conn.cursor()
            
            now = datetime.now(timezone.utc)
            now_str = now.isoformat()
            
            # Get existing binding for this hotkey
            cursor.execute(
                "SELECT user_id, first_seen_at FROM user_hotkey_bindings WHERE hotkey = ?",
                (hotkey,)
            )
            existing = cursor.fetchone()
            
            if existing is None:
                # No existing binding - create new one
                cursor.execute(
                    """
                    INSERT INTO user_hotkey_bindings 
                    (user_id, hotkey, first_seen_at, last_updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, hotkey, now_str, now_str)
                )
                conn.commit()
                conn.close()
                
                if user_id:
                    logger.debug(
                        f"New user-hotkey binding: user={user_id[:16]}... -> hotkey={hotkey[:16]}..."
                    )
                else:
                    logger.debug(f"New hotkey tracked (no userId): hotkey={hotkey[:16]}...")
                
                return None, True  # New hotkey, no previous userId
            
            # Existing binding found
            existing_user_id = existing[0]  # user_id column
            
            # Check if userId has changed
            if existing_user_id == user_id:
                # Same user (or both None) - just update timestamp
                cursor.execute(
                    "UPDATE user_hotkey_bindings SET last_updated_at = ? WHERE hotkey = ?",
                    (now_str, hotkey)
                )
                conn.commit()
                conn.close()
                return None, False  # No change
            
            # userId has changed - update binding and record previous
            cursor.execute(
                """
                UPDATE user_hotkey_bindings 
                SET user_id = ?, last_updated_at = ?, previous_user_id = ?
                WHERE hotkey = ?
                """,
                (user_id, now_str, existing_user_id, hotkey)
            )
            conn.commit()
            conn.close()
            
            # Return the previous userId (only if it was non-None)
            return existing_user_id, False
            
        except Exception as e:
            logger.error(f"Failed to update binding for hotkey {hotkey}: {e}")
            return None, False
