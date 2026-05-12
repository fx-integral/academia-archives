import os
import time
import asyncio
import utils.logger as logger
from datetime import datetime, timezone
from bittensor_wallet import Wallet
from models.validator_upload_request import ValidatorUploadRequest
from utils.r2 import put_r2_upload
from utils.subtensor import get_subtensor

  
async def r2_sync():
    """
    Periodically sync evals to R2
    """        
    logger.info(f"\033[35mR2 sync ran at {int(time.time())}\033[0m")

    NETUID = int(os.getenv("NETUID", 296))
    VALIDATOR_WALLET_NAME = os.environ.get("VALIDATOR_WALLET_NAME", "")
    VALIDATOR_HOTKEY_NAME = os.environ.get("VALIDATOR_HOTKEY_NAME", "")
    wallet = Wallet(VALIDATOR_WALLET_NAME, VALIDATOR_HOTKEY_NAME)
    
    sub = await get_subtensor()
    uid = await sub.get_uid_for_hotkey_on_subnet(hotkey_ss58=wallet.hotkey.ss58_address, netuid=NETUID)

    start_time = time.perf_counter()    
    if not wallet or not wallet.hotkey:
        logger.error("Hotkey not found - skipping R2 sync")
        return
    try:
        keypair = wallet.hotkey
        logger.debug(f"R2 upload uid {uid} with address: {keypair.ss58_address}")
        update_request = ValidatorUploadRequest(
            created_at=datetime.now(timezone.utc).isoformat(),  
            hotkey=keypair.ss58_address,
            uid=uid
        )
        logger.debug(f"Sending response sync request: {update_request}")        
        loop = asyncio.get_event_loop()
        sync_result = await loop.run_in_executor(
            None,
            lambda: put_r2_upload(update_request, keypair)
        )
        if sync_result:
            logger.info(f"\033[1;32m Success - R2 updated sync_result: {sync_result} \033[0m")
        else:
            logger.error("\033[1;31m Failed to update R2 \033[0m")

    except Exception as e:
        logger.error(f"Failed to update R2 with exception: {e}")
    finally:
        duration = time.perf_counter() - start_time
        logger.info(f"R2 Sync complete in {duration:.2f} seconds")