import os
import boto3
import traceback
import asyncio
import datetime 
import sqlite3
import utils.logger as logger
from api import config
from typing import Optional
from utils.database import db_operation
from botocore.config import Config
from utils.validator_hotkeys import TEST_VALIDATOR_HOTKEYS, MAINNET_VALIDATOR_HOTKEYS

R2_INTERVAL_SECONDS = 900

async def r2_download_and_sync():
    await asyncio.sleep(300)
    IS_MAINNET = os.getenv("ENV", "").lower() == "prod"
    logger.info(f"Starting r2_download_and_sync loop... Environment: {'Mainnet' if IS_MAINNET else 'Testnet'}")
    while True:
        try:
            VALIDATOR_KEYS = MAINNET_VALIDATOR_HOTKEYS if IS_MAINNET else TEST_VALIDATOR_HOTKEYS
            for hotkey in VALIDATOR_KEYS:
                r2_key = f"{hotkey}/scores.db"
                local_db_path = download_db_from_r2(bucket_name=config.R2_BUCKET_NAME, key=r2_key, download_dir="/tmp")
                if local_db_path:
                    await upsert_to_postgres(sqlite_path=local_db_path, validator_hotkey=hotkey)
                    os.remove(local_db_path)
        except Exception as e:
            logger.error(f"Error in validator heartbeat timeout loop: {e}")
            logger.error(traceback.format_exc())
        
        await asyncio.sleep(R2_INTERVAL_SECONDS)



def download_db_from_r2(bucket_name: str, key: str, download_dir: str, region: str = "wnam") -> Optional[str]:
    if not os.path.exists(download_dir):
        logger.error(f"Directory not found: {download_dir}")
        return None
    
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
            endpoint_url=os.getenv("R2_ENDPOINT_URL"),
            config=Config(signature_version="s3v4", region_name=region)
        )
        
        local_sqlite_file = os.path.join(download_dir, f"{os.path.basename(key).replace('/scores.db', '')}_scores.sqlite")
        logger.info(f"Downloading {bucket_name}/{key} to {local_sqlite_file}")
        s3.download_file(bucket_name, key, local_sqlite_file)
        logger.info("Download complete")
        return local_sqlite_file
    except Exception as e:
        logger.error(f"Failed to download from R2: {e}")
        return None

@db_operation
async def upsert_to_postgres(conn, sqlite_path: str, validator_hotkey: str) -> None:   
    try:        
        if not validator_hotkey:
            raise ValueError("Validator hotkey is required for upsert")
        sqlite_conn = sqlite3.connect(sqlite_path)
        cursor = sqlite_conn.cursor()
        cursor.execute("SELECT run_id, uid, hotkey, task_name, score, success, duration, created_at, evaluation_set_id, sample_size FROM miner_scores")
        rows = cursor.fetchall()        
        if not rows:
            logger.info("No rows to upsert")
            return        
        
        data = [
            (
                row[0],  # run_id
                row[1],  # uid
                row[2],  # hotkey
                row[3],  # task_name
                row[4],  # score
                bool(row[5]),  # success
                row[6],  # duration
                datetime.datetime.fromisoformat(row[7].replace('Z', '+00:00')),  # created_at
                row[8],  # evaluation_set_id
                row[9],   # sample_size
                validator_hotkey 
            )
            for row in rows
        ]        
        
        upsert_query = """
        INSERT INTO miner_scores (run_id, uid, hotkey, task_name, score, success, duration, created_at, evaluation_set_id, sample_size, validator_hotkey)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (run_id) DO NOTHING
        """
        
        await conn.executemany(upsert_query, data)
        logger.info(f"Upserted {len(rows)} rows into PostgreSQL")
        
        sqlite_conn.close()
    except Exception as e:
        logger.error(f"Failed to upsert to PostgreSQL: {e}")
        raise  # Re-raise to let @db_operation handle rollback if needed

