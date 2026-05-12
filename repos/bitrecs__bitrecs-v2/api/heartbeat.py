import asyncio
import traceback
from api import config
from utils import logger
from api.endpoints.validator import delete_validators_that_have_not_sent_a_heartbeat

async def validator_heartbeat_timeout_loop():
    logger.info("Starting validator heartbeat timeout loop...")
    while True:
        try:            
            await delete_validators_that_have_not_sent_a_heartbeat() 
        except Exception as e:
            logger.error(f"Error in validator heartbeat timeout loop: {e}")
            logger.error(traceback.format_exc())
        
        await asyncio.sleep(config.VALIDATOR_HEARTBEAT_TIMEOUT_INTERVAL_SECONDS)
