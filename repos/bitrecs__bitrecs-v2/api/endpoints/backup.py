import os
import json
import utils.logger as logger
from bittensor_wallet import Keypair
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from api.utils.limiter import limiter
from utils.network import get_client_ip
from utils.r2 import is_valid_url
from utils.verify import verify_timestamp
from models.validator_upload_request import ValidatorUploadRequest

router = APIRouter()


def generate_upload_url2(report: ValidatorUploadRequest) -> str:
    try:
        from boto3 import client
        from botocore.client import Config
        
        R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID")
        R2_SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
        R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
        R2_BUCKET = os.environ.get("R2_BUCKET_NAME")

        if not all([R2_ACCESS_KEY, R2_SECRET_KEY, R2_ENDPOINT_URL, R2_BUCKET]):
            logger.error("Missing R2 configuration")
            raise HTTPException(status_code=500, detail="Storage configuration error")

        logger.info(f"Generating presigned upload url for validator: {report.hotkey}")
        r2_key = f"{report.hotkey}/scores.db"
        r2_client = client(
            's3',
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version="s3v4", region_name="wnam")
        )    
        # Generate presigned URL
        signed_url = r2_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': R2_BUCKET,
                'Key': r2_key,
                'ContentType': 'application/x-sqlite3'
            },
            ExpiresIn=1800
        )
        return signed_url    
    except Exception as e:
       logger.error(f"Upload URL generation failed: {str(e)}")
       raise HTTPException(status_code=500, detail="Failed to generate upload URL")



# /backup/upload-request
@router.post("/upload-request")
@limiter.limit("60/minute")
async def upload_request(request: Request, report: ValidatorUploadRequest):
    try:        
        client_ip = get_client_ip(request)
        logger.info(f"Validator upload request from IP: {client_ip}")

        timestamp = request.headers.get("X-Timestamp")
        signature = request.headers.get("X-Signature")
        nonce = request.headers.get("X-Nonce")
        if not all([timestamp, signature, nonce]):
            logger.warning(f"Missing headers from {client_ip}")
            raise HTTPException(status_code=400, detail="Missing required headers")
        
        if not verify_timestamp(timestamp):
            logger.warning(f"Invalid timestamp from {client_ip}")
            raise HTTPException(status_code=400, detail="Invalid timestamp")

        report_json = json.dumps(report.to_dict(), sort_keys=True)
        components = [
            str(timestamp),
            report.hotkey,
            report_json,
            nonce
        ]
        message = '.'.join(components).encode('utf-8')
        keypair = Keypair(ss58_address=report.hotkey)
        signature_bytes = bytes.fromhex(signature)
        verified = keypair.verify(message, signature_bytes)        
        if not verified:
            logger.warning(f"Invalid signature from {client_ip}")
            raise HTTPException(status_code=403, detail="Invalid signature")
            
        logger.info(f"Validator upload Valid signature from {report.hotkey} at IP: {client_ip}")        
        signed_url = generate_upload_url2(report)
        if not signed_url or not is_valid_url(signed_url):
            raise HTTPException(status_code=500, detail="Failed to generate upload URL")
        
        return JSONResponse(content={
            "signed_url": signed_url,
            "expires_in": 1800,
            "status": "success"
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


