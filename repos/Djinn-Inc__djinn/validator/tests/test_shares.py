"""Tests for the ShareStore."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from djinn_validator.core.shares import ShareStore
from djinn_validator.utils.crypto import Share


class TestShareStore:
    def setup_method(self) -> None:
        self.store = ShareStore()

    def test_store_and_retrieve(self) -> None:
        share = Share(x=1, y=12345)
        self.store.store("sig-1", "0xGenius", share, b"encrypted-key")
        record = self.store.get("sig-1")
        assert record is not None
        assert record.genius_address == "0xGenius"
        assert record.share == share
        assert record.encrypted_key_share == b"encrypted-key"

    def test_has(self) -> None:
        assert not self.store.has("sig-1")
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        assert self.store.has("sig-1")

    def test_release(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"secret")
        data = self.store.release("sig-1", "0xBuyer")
        assert data == b"secret"

    def test_release_nonexistent(self) -> None:
        assert self.store.release("nonexistent", "0xB") is None

    def test_double_release(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        self.store.release("sig-1", "0xB")
        # Second release still returns the key
        data = self.store.release("sig-1", "0xB")
        assert data == b"key"

    def test_remove(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        self.store.remove("sig-1")
        assert not self.store.has("sig-1")

    def test_count(self) -> None:
        assert self.store.count == 0
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"a")
        self.store.store("sig-2", "0xG", Share(x=2, y=2), b"b")
        assert self.store.count == 2

    def test_active_signals(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"a")
        self.store.store("sig-2", "0xG", Share(x=2, y=2), b"b")
        signals = self.store.active_signals()
        assert set(signals) == {"sig-1", "sig-2"}

    def test_duplicate_store_raises(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"first")
        with pytest.raises(ValueError, match="already stored"):
            self.store.store("sig-1", "0xG", Share(x=1, y=999), b"second")
        # Original should be preserved
        record = self.store.get("sig-1")
        assert record is not None
        assert record.encrypted_key_share == b"first"


class TestShareStoreRetry:
    def test_connect_retries_on_failure(self) -> None:
        """Verify retry logic calls sqlite3.connect multiple times on failure."""
        real_connect = sqlite3.connect
        call_count = 0

        def flaky_connect(path: str, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            return real_connect(":memory:", **kwargs)

        with patch("sqlite3.connect", side_effect=flaky_connect):
            with patch("time.sleep"):  # Skip actual delay
                conn = ShareStore._connect_with_retry("/fake/path.db")
        assert call_count == 3
        conn.close()

    def test_connect_gives_up_after_max_retries(self) -> None:
        """After max retries, the error is raised."""
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("locked")):
            with patch("time.sleep"):
                import pytest

                with pytest.raises(sqlite3.OperationalError):
                    ShareStore._connect_with_retry("/fake/path.db")


class TestShareStorePersistence:
    """Test that shares survive across ShareStore instances (file-backed SQLite)."""

    def test_data_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "shares.db"

            # First instance: store a share
            store1 = ShareStore(db_path=db_path)
            store1.store("sig-1", "0xGenius", Share(x=3, y=99999), b"secret-key")
            store1.release("sig-1", "0xBuyer1")
            store1.close()

            # Second instance: verify data persists
            store2 = ShareStore(db_path=db_path)
            assert store2.has("sig-1")
            assert store2.count == 1

            record = store2.get("sig-1")
            assert record is not None
            assert record.genius_address == "0xGenius"
            assert record.share == Share(x=3, y=99999)
            assert record.encrypted_key_share == b"secret-key"
            assert "0xBuyer1" in record.released_to

            # Double-release still works
            data = store2.release("sig-1", "0xBuyer1")
            assert data == b"secret-key"

            store2.close()

    def test_remove_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "shares.db"

            store = ShareStore(db_path=db_path)
            store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
            store.remove("sig-1")
            store.close()

            store2 = ShareStore(db_path=db_path)
            assert not store2.has("sig-1")
            assert store2.count == 0
            store2.close()


class TestShareStoreInputValidation:
    """Input validation on store and release."""

    def setup_method(self) -> None:
        self.store = ShareStore()

    def test_store_empty_signal_id_raises(self) -> None:
        with pytest.raises(ValueError, match="signal_id"):
            self.store.store("", "0xG", Share(x=1, y=1), b"key")

    def test_store_whitespace_signal_id_raises(self) -> None:
        with pytest.raises(ValueError, match="signal_id"):
            self.store.store("   ", "0xG", Share(x=1, y=1), b"key")

    def test_store_empty_genius_address_raises(self) -> None:
        with pytest.raises(ValueError, match="genius_address"):
            self.store.store("sig-1", "", Share(x=1, y=1), b"key")

    def test_store_empty_encrypted_key_raises(self) -> None:
        with pytest.raises(ValueError, match="encrypted_key_share"):
            self.store.store("sig-1", "0xG", Share(x=1, y=1), b"")

    def test_release_empty_signal_id_returns_none(self) -> None:
        assert self.store.release("", "0xBuyer") is None

    def test_release_empty_buyer_returns_none(self) -> None:
        self.store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        assert self.store.release("sig-1", "") is None


class TestShareStoreCloseSafety:
    """Verify close is idempotent and sets connection to None."""

    def test_close_idempotent(self) -> None:
        store = ShareStore()
        store.close()
        store.close()  # Should not raise

    def test_close_sets_conn_none(self) -> None:
        store = ShareStore()
        store.close()
        assert store._conn is None


class TestShareStoreReleaseAtomicity:
    """Verify release transaction atomicity."""

    def test_release_to_multiple_buyers(self) -> None:
        """Different buyers can each get the share."""
        store = ShareStore()
        store.store("sig-1", "0xG", Share(x=1, y=1), b"secret")
        assert store.release("sig-1", "0xBuyer1") == b"secret"
        assert store.release("sig-1", "0xBuyer2") == b"secret"
        record = store.get("sig-1")
        assert record is not None
        assert record.released_to == {"0xBuyer1", "0xBuyer2"}

    def test_release_records_buyer_in_released_to(self) -> None:
        store = ShareStore()
        store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        store.release("sig-1", "0xBuyer")
        record = store.get("sig-1")
        assert record is not None
        assert "0xBuyer" in record.released_to

    def test_remove_cascades_releases(self) -> None:
        """Removing a share should also remove its release records."""
        store = ShareStore()
        store.store("sig-1", "0xG", Share(x=1, y=1), b"key")
        store.release("sig-1", "0xBuyer")
        store.remove("sig-1")
        assert not store.has("sig-1")
        # Re-add and verify no stale releases
        store.store("sig-1", "0xG", Share(x=2, y=2), b"new")
        record = store.get("sig-1")
        assert record is not None
        assert record.released_to == set()


class TestShareStoreSignalIdValidation:
    """ShareStore.store() must reject invalid signal IDs."""

    def setup_method(self) -> None:
        self.store = ShareStore()

    def test_valid_id_accepted(self) -> None:
        self.store.store("valid-signal_123", "0xG", Share(x=1, y=1), b"key")
        assert self.store.has("valid-signal_123")

    def test_colon_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid signal_id"):
            self.store.store("sig:evil", "0xG", Share(x=1, y=1), b"key")

    def test_slash_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid signal_id"):
            self.store.store("sig/path", "0xG", Share(x=1, y=1), b"key")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid signal_id"):
            self.store.store("", "0xG", Share(x=1, y=1), b"key")

    def test_spaces_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid signal_id"):
            self.store.store("sig id", "0xG", Share(x=1, y=1), b"key")


class TestShareStoreThreadSafety:
    """ShareStore operations are safe under concurrent access."""

    def setup_method(self) -> None:
        self.store = ShareStore()

    def test_concurrent_store_and_release(self) -> None:
        import threading

        errors: list[Exception] = []

        def store_signals(start: int, count: int) -> None:
            for i in range(start, start + count):
                try:
                    self.store.store(f"sig-{i}", "0xGenius", Share(x=i + 1, y=i * 100), b"key-data")
                except Exception as e:
                    errors.append(e)

        def release_signals(start: int, count: int) -> None:
            for i in range(start, start + count):
                try:
                    self.store.release(f"sig-{i}", "0xBuyer")
                except Exception as e:
                    errors.append(e)

        # Store 50 signals first
        store_signals(0, 50)

        # Concurrently store more and release existing
        threads = [
            threading.Thread(target=store_signals, args=(50, 50)),
            threading.Thread(target=release_signals, args=(0, 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert self.store.count == 100
