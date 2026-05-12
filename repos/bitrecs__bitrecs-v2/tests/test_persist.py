import pytest
import tempfile
from pathlib import Path
from scoring.persist import ScorePersister


@pytest.fixture
def temp_db():
    """Create a temporary SQLite DB for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)  # Cleanup


@pytest.fixture
def persister(temp_db):
    """Fixture for ScorePersister with a temp DB."""
    p = ScorePersister(base_path=str(temp_db.parent), filename=temp_db.name.split('/')[-1])
    return p


def test_update_schema_adds_missing_column(persister, caplog):
    """Test that update_schema adds a missing column and logs it."""
    columns = {'new_col': 'TEXT'}

    persister.update_schema('miner_scores', columns)

    # Verify column was added
    with persister._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(miner_scores)")
        columns_info = cursor.fetchall()
        column_names = [col[1] for col in columns_info]
        assert 'new_col' in column_names
    assert "Added column 'new_col'" in caplog.text


def test_update_schema_skips_existing_column(persister):
    """Test that update_schema skips an existing column."""
    # 'uid' already exists from _init_db
    columns = {'uid': 'INTEGER'}  # Existing column

    persister.update_schema('miner_scores', columns)

    # Verify no duplicate addition (check logs or just that it doesn't error)


def test_update_schema_handles_multiple_columns(persister, caplog):
    """Test that update_schema processes multiple columns."""
    columns = {'col1': 'TEXT', 'col2': 'INTEGER'}

    persister.update_schema('miner_scores', columns)

    with persister._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(miner_scores)")
        columns_info = cursor.fetchall()
        column_names = [col[1] for col in columns_info]
        assert 'col1' in column_names
        assert 'col2' in column_names
    assert "Added column 'col1'" in caplog.text
    assert "Added column 'col2'" in caplog.text


def test_update_schema_empty_columns(persister):
    """Test that update_schema handles empty columns dict."""
    persister.update_schema('miner_scores', {})

    # Should do nothing without error


def test_save_result_inserts_row(persister):
    """Test that save_result inserts a row."""
    result = persister.save_result(
        uid=1,
        hotkey='hotkey1',
        score=1.0,
        run_id='run1',
        task_name='task1',
        success=True,
        duration=10.0,
        evaluation_set_id=123,
        sample_size=5
    )

    assert result is True  # Should return True on success

    # Verify row was inserted
    with persister._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM miner_scores WHERE uid = ?", (1,))
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == 1  # uid
        assert row[2] == 'hotkey1'
        assert row[4] == 1.0  # score
        assert row[0] == 'run1'  # run_id