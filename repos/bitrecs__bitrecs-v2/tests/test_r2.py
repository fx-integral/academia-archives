import os
import random
import time
import httpx
import httpx
import pytest
import secrets
from bittensor_wallet import Wallet
from datetime import datetime, timezone
from models.validator_upload_request import ValidatorUploadRequest
from utils.r2 import (
    create_upload_request_message, put_r2_upload, 
    upload_file_to_r2, upload_text_file_to_r2, 
    download_text_file_from_r2, validate_r2_bucket_connection
)
from utils.validator_hotkeys import WHITELISTED_VALIDATORS

TEST_BUCKET = os.getenv("R2_BUCKET_NAME")
TEST_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
TEST_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
TEST_ENDPOINT = os.getenv("R2_ENDPOINT_URL")
TEST_PATH = "test-integration-file.txt"
TEST_TEXT = f"Integration test content! - {secrets.token_hex(8)}"


def get_random_key():
    c = random.choice(WHITELISTED_VALIDATORS)
    return c.get("hotkey")


@pytest.mark.asyncio
async def test_r2_connection_basic():
    result = await validate_r2_bucket_connection(
        TEST_BUCKET, 
        TEST_ACCESS_KEY, 
        TEST_SECRET_KEY, 
        TEST_ENDPOINT
    )
    assert result is True


@pytest.mark.asyncio
async def test_r2_upload_download_integration():
    """Integration test: Upload and download a real file to/from R2."""
    if not all([TEST_BUCKET, TEST_ACCESS_KEY, TEST_SECRET_KEY, TEST_ENDPOINT]):
        pytest.skip("R2 credentials not set in environment. Set R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL.")    
    
    await upload_text_file_to_r2(TEST_BUCKET, TEST_ACCESS_KEY, TEST_SECRET_KEY, TEST_ENDPOINT, TEST_PATH, TEST_TEXT)
    downloaded_text = await download_text_file_from_r2(TEST_BUCKET, TEST_ACCESS_KEY, TEST_SECRET_KEY, TEST_ENDPOINT, TEST_PATH)    
    assert downloaded_text == TEST_TEXT


@pytest.mark.asyncio
async def test_r2_scores_backup():
    """Test backup of scores to R2."""
    from pathlib import Path
    root_path = Path(__file__).parent.parent.absolute()       
    db_path = root_path / "scores.db" 
    if not db_path.exists():
        pytest.skip("Scores DB not found. Run scoring engine at least once to generate scores.db for this test.")
    
    validator_key = get_random_key()
    upload_path = f"{validator_key}/scores.db"
    upload_success = await upload_file_to_r2(bucket="v2-testnet", 
                      access_key_id=TEST_ACCESS_KEY, 
                      secret_access_key=TEST_SECRET_KEY, 
                      endpoint_url=TEST_ENDPOINT, 
                      path=upload_path, 
                      file_content=db_path.read_bytes(), 
                      content_type="application/octet-stream")    
    assert upload_success is True   


def test_validator_backup_r2_signed_request():
    SERVICE_URL = "http://localhost:8000"    
    MINER_WALLET_NAME = os.getenv("MINER_WALLET_NAME")
    MINER_WALLET_HOTKEY_NAME = os.getenv("MINER_WALLET_HOTKEY_NAME")
    wallet = Wallet(name=MINER_WALLET_NAME, hotkey=MINER_WALLET_HOTKEY_NAME)    
    report = ValidatorUploadRequest(
        created_at=datetime.now(timezone.utc).isoformat(),
        hotkey=wallet.hotkey.ss58_address,
        uid=10
    )    
    timestamp = int(time.time())
    message, nonce = create_upload_request_message(timestamp, report)
    signature = wallet.hotkey.sign(message).hex()
    report_dict = report.to_dict()
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Signature': signature,
        'X-Timestamp': str(timestamp),
        'X-Nonce': nonce,
        'X-API-Key': os.getenv("BITRECS_PLATFORM_API_KEY")
    }

    with httpx.Client() as client:
        response = client.post(f"{SERVICE_URL}/backup/upload-request", json=report_dict, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "signed_url" in data
        upload_url = data["signed_url"]
        assert upload_url.startswith("https")

  
def test_validator_backup_r2_via_url():
    MINER_WALLET_NAME = os.getenv("MINER_WALLET_NAME")
    MINER_WALLET_HOTKEY_NAME = os.getenv("MINER_WALLET_HOTKEY_NAME")
    wallet = Wallet(name=MINER_WALLET_NAME, hotkey=MINER_WALLET_HOTKEY_NAME)    
    upload_request = ValidatorUploadRequest(
        created_at=datetime.now(timezone.utc).isoformat(),
        hotkey=wallet.hotkey.ss58_address,
        uid=10
    )
    uploaded = put_r2_upload(upload_request, wallet.hotkey) 
    assert uploaded is True


@pytest.mark.asyncio
async def test_r2_download_and_sync_to_postgres(db_setup):
    """Unit test: Download scores.db from R2 for a random validator and sync to PostgreSQL."""
    if not all([os.getenv("R2_BUCKET_NAME"), os.getenv("R2_ACCESS_KEY_ID"), os.getenv("R2_SECRET_ACCESS_KEY"), os.getenv("R2_ENDPOINT_URL")]):
        pytest.skip("R2 credentials not set in environment.")
    
    test_validators = ["5FNL6e4JsB3ZPUGk1x1izK1xnTWsZDZrVF6WaRp1gNpoTvsM", "5FtH6Aj3xKbkNdgbZUghkTeJrkJexn6eBRZSnS8Zgc3oo4GX", "5Eyj7B2PzUMzRpW59eXziw4LazsQkn8bESF5gnbchyTdZEhX"]    
    hotkey = random.choice(test_validators)
    r2_key = f"{hotkey}/scores.db"    
    
    import tempfile
    download_dir = tempfile.mkdtemp()
    
    # Download from R2
    from api.db_sync import download_db_from_r2, upsert_to_postgres
    db_path = download_db_from_r2("v2-testnet", r2_key, download_dir)
    assert db_path is not None, f"Failed to download {r2_key}"
    
    try:
        # Count rows before upsert
        from utils.database import db_operation
        @db_operation
        async def count_rows_before(conn):
            result = await conn.fetchval("SELECT COUNT(*) FROM miner_scores")
            return result
        count_before = await count_rows_before()
        
        # Upsert to PostgreSQL
        await upsert_to_postgres(db_path, hotkey)
        
        # Count rows after upsert
        @db_operation
        async def count_rows_after(conn):
            result = await conn.fetchval("SELECT COUNT(*) FROM miner_scores")
            return result
        count_after = await count_rows_after()
        
        # Assert rows were added/updated (at least 1 row expected)
        assert count_after > count_before, "No rows were upserted"
    finally:
        # Clean up temp file and dir
        import shutil
        if os.path.exists(db_path):
            os.unlink(db_path)
        shutil.rmtree(download_dir)