import re
import api.config as config
from utils.subtensor import get_subtensor

async def check_if_hotkey_is_registered(hotkey: str) -> bool:
    subtensor = await get_subtensor()    
    return await subtensor.is_hotkey_registered(hotkey_ss58=hotkey, netuid=config.NETUID)    
    
def is_hotkey_valid_format(hotkey: str) -> bool:
    if not isinstance(hotkey, str) or len(hotkey) != 48:
        return False    
    pattern = r"^5[1-9A-HJ-NP-Za-km-z]{47}$"
    if re.match(pattern, hotkey):
        return True
    return False