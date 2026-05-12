import utils.logger as logger
from fastapi import HTTPException
from queries.rate_limit import get_current_rate
from queries.hotkey_gist import get_hotkey_from_gist
from api.config import ARTIFACTS_PER_INTERVAL
from queries.banned_hotkey import get_banned_hotkey, is_hotkey_used
from utils.bittensor import check_if_hotkey_is_registered
from utils.validator_hotkeys import WHITELISTED_VALIDATORS


async def check_if_hotkey_is_validator(hotkey: str) -> None:
    match = [w for w in WHITELISTED_VALIDATORS if w["hotkey"] == hotkey]
    if match:
        logger.error(f"A miner attempted to upload an agent with a hotkey that belongs to a whitelisted validator: {hotkey}.")
        raise HTTPException(
            status_code=400,
            detail="Hotkey belongs to a whitelisted validator and cannot be used for agent submission. Please register a new hotkey"
        )   


async def check_if_hotkey_used(hotkey: str) -> None:
    is_used = await is_hotkey_used(hotkey)
    if is_used:
        logger.error(f"A miner attempted to upload an agent with a hotkey that is already in use: {hotkey}.")
        raise HTTPException(
            status_code=400,
            detail="Hotkey has already been used for an agent submission. Please register a new hotkey"
        )
    
async def check_if_gist_used(gist: str) -> None:
    hotkey = await get_hotkey_from_gist(gist)
    if hotkey is not None:
        logger.error(f"A miner attempted to upload an agent with a gist that is already in use: {gist}.")
        raise HTTPException(
            status_code=400,
            detail="Gist has already been used for an agent submission. Please create a new gist"
        )


async def check_agent_banned(miner_hotkey: str) -> None:
    logger.debug(f"Checking if miner hotkey {miner_hotkey} is banned...")

    if await get_banned_hotkey(miner_hotkey) is not None:
        logger.error(f"A miner attempted to upload an agent with a banned hotkey: {miner_hotkey}.")
        raise HTTPException(
            status_code=403,
            detail="Your miner hotkey has been banned. If this is in error, please contact us on Discord"
        )
    
    logger.debug(f"Miner hotkey {miner_hotkey} is not banned.")



async def check_rate_limit() -> None:
    logger.debug(f"Checking system rate limit..")
    current = await get_current_rate()
    logger.debug(f"Current number of agents created in interval: {current}. Limit: {ARTIFACTS_PER_INTERVAL}.")
    if current >= ARTIFACTS_PER_INTERVAL:
        logger.error(f"System is currently rate limited. Number of agents created in interval: {current}. Limit: {ARTIFACTS_PER_INTERVAL}.")
        raise HTTPException(
            status_code=429,
            detail="The system is currently receiving too many agent submissions. Please try again later."
        )


async def check_hotkey_registered(miner_hotkey: str) -> None:
    logger.debug(f"Checking if miner hotkey {miner_hotkey} is registered on subnet...")
    if not await check_if_hotkey_is_registered(miner_hotkey):
        logger.error(f"A miner attempted to upload an agent with a hotkey that is not registered on subnet: {miner_hotkey}.")
        raise HTTPException(status_code=400, detail=f"Hotkey not registered on subnet")    
    logger.debug(f"Miner hotkey {miner_hotkey} is registered on the subnet.")




