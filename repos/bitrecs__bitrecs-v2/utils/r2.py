import time
import json
import os
import secrets
import aioboto3
import requests
import utils.logger as logger
from urllib.parse import urlparse
from bittensor_wallet import Keypair
from typing import Tuple
from models.validator_upload_request import ValidatorUploadRequest


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def create_r2_client(bucket: str, access_key_id: str, secret_access_key: str, endpoint_url: str):
    """Factory to create an R2 client on demand."""
    session = aioboto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key
    )
    return session.client('s3', endpoint_url=endpoint_url, region_name='auto')

async def validate_r2_bucket_connection(bucket: str, access_key_id: str, secret_access_key: str, endpoint_url: str) -> bool:
    """
    Test R2 connection by attempting to access the bucket.
    Returns True if successful, raises exception on failure.
    Useful for startup validation to catch config issues early.
    """
    try:
        async with create_r2_client(bucket, access_key_id, secret_access_key, endpoint_url) as s3_client:
            logger.info(f"Testing R2 connection to bucket: {bucket}")
            # Use head_bucket to check bucket existence and access (lightweight)
            await s3_client.head_bucket(Bucket=bucket)
            logger.info(f"R2 connection test successful for bucket: {bucket}")
            return True
    except Exception as e:
        logger.error(f"R2 connection test failed for bucket {bucket}: {e}")
        raise RuntimeError(f"R2 connection test failed: {e}") from e
    
async def upload_file_to_r2(bucket: str, access_key_id: str, secret_access_key: str, endpoint_url: str, path: str, file_content: bytes, content_type: str) -> bool:
    try:
        async with create_r2_client(bucket, access_key_id, secret_access_key, endpoint_url) as s3_client:
            logger.info(f"Uploading file to r2://{bucket}/{path}")
            await s3_client.put_object(
                Bucket=bucket, 
                Key=path, 
                Body=file_content, 
                ContentType=content_type
            )
            logger.info(f"Successfully uploaded file to r2://{bucket}/{path}")
            return True
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise    

async def upload_text_file_to_r2(bucket: str, access_key_id: str, secret_access_key: str, endpoint_url: str, path: str, text: str):
    try:
        async with create_r2_client(bucket, access_key_id, secret_access_key, endpoint_url) as s3_client:
            logger.info(f"Uploading text file to r2://{bucket}/{path}")
            await s3_client.put_object(
                Bucket=bucket, 
                Key=path, 
                Body=text.encode('utf-8'), 
                ContentType='text/plain'
            )
            logger.info(f"Successfully uploaded text file to r2://{bucket}/{path}")
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise

async def download_text_file_from_r2(bucket: str, access_key_id: str, secret_access_key: str, endpoint_url: str, path: str) -> str:
    try:
        async with create_r2_client(bucket, access_key_id, secret_access_key, endpoint_url) as s3_client:
            logger.info(f"Downloading text file from r2://{bucket}/{path}")
            response = await s3_client.get_object(Bucket=bucket, Key=path)
            body = await response['Body'].read()
            content = body.decode('utf-8')
            logger.info(f"Successfully downloaded text file from r2://{bucket}/{path}")
            return content
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise


def create_upload_request_message(timestamp: int, report: ValidatorUploadRequest) -> Tuple[bytes, str]:
    nonce = secrets.token_hex(16)
    report_json = json.dumps(report.to_dict(), sort_keys=True)
    components = [
        str(timestamp),
        report.hotkey,
        report_json,
        nonce
    ]
    message = '.'.join(components)
    return message.encode('utf-8'), nonce


def get_r2_upload_url(report: ValidatorUploadRequest, keypair: Keypair) -> str:    
    platform_url = os.environ.get("BITRECS_PLATFORM_URL", "")
    #platform_url = "http://localhost:8000"

    request_url = f"{platform_url}/backup/upload-request"
    timestamp = int(time.time())
    message, nonce = create_upload_request_message(timestamp, report)
    sig = keypair.sign(message).hex()
    report_dict = report.to_dict()
    headers = {
        'Content-Type': 'application/json',      
        'X-API-Key': os.environ.get("BITRECS_PLATFORM_API_KEY"),
        'X-Signature': sig,
        'X-Timestamp': str(timestamp),
        'X-Nonce': nonce
    }
    try:
        response = requests.post(
            request_url, 
            json=report_dict,
            headers=headers
        )
        if response.status_code == 200:
            result = response.json()
            if "signed_url" in result:
                return result["signed_url"]
            else:
                logger.error("No signed_url in response")
                logger.debug("Response:", json.dumps(result, indent=2))
                return ""
        else:            
            logger.error(f"Request failed with status code: {response.status_code}")
            logger.error(response.text)
            return ""

    except requests.exceptions.RequestException as e:        
        logger.error(f"An error occurred: {e}")
        return ""
    

def put_r2_upload(request: ValidatorUploadRequest, keypair: Keypair) -> bool:
    if not request or not keypair:
        return False    
    from pathlib import Path
    db_path = Path("data/weights/scores.db")
    if not db_path.exists():
        logger.error("Scores DB not found. Run scoring engine at least once to generate scores.db for upload.")
        return False
    if db_path.stat().st_size == 0:
        logger.error("Scores DB is empty. Upload aborted.")
        return False   
    
    signed_url = get_r2_upload_url(request, keypair)
    if not is_valid_url(signed_url):
        logger.error("Failed to get signed URL")
        return False    
    logger.info("STARTING UPLOAD -----------------------------------------")
    try: 
        with db_path.open('rb') as f:
            file_data = f.read()      
        headers = {
            'Content-Type': 'application/x-sqlite3',
            'Content-Length': str(len(file_data))
        }
        response = requests.put(
            signed_url,
            data=file_data,
            headers=headers,
            timeout=900
        )
        if response.status_code in (200, 201):
            logger.info("Successfully uploaded to R2")
            logger.info("FINISHED UPLOAD SUCCESS -----------------------------------------")
            return True
        else:
            logger.error(f"Upload failed with status code: {response.status_code}")
            logger.error("Response headers:", dict(response.headers))
            logger.error("Response body:", response.text)
            logger.info("FINISHED UPLOAD FAILURE -----------------------------------------")
            return False                    
    except requests.exceptions.RequestException as e:        
        logger.error(f"Upload request failed: {str(e)}")
        return False
    except IOError as e:        
        logger.error(f"File operation failed: {str(e)}")
        return False
    except Exception as e:        
        logger.error(f"Unexpected error: {str(e)}")
        return False