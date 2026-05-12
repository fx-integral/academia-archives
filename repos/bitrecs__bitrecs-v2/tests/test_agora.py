import os
from dotenv import load_dotenv
load_dotenv()

MINER_WALLET_HOTKEY = os.getenv("MINER_WALLET_HOTKEY")

async def test_post_to_agora():
    from utils.agora import post_to_agora, AgoraStatus
    payload = AgoraStatus(id="api", from_server="ops", priority=1, description="All systems normal.", status="ok")
    posted = await post_to_agora(payload)
    assert posted, "Failed to post to Agora"

async def test_post_to_agora2():
    from utils.agora import post_to_agora, AgoraStatus
    weight_info = {"uid0": 0.5, "uid1": 0.3, "uid2": 0.2}
    payload = AgoraStatus(id="api", from_server=MINER_WALLET_HOTKEY, priority=1, description=str(weight_info), status="ok")
    posted = await post_to_agora(payload)
    assert posted, "Failed to post to Agora"

async def test_post_to_agora3():
    from utils.agora import post_to_agora, AgoraStatus
    weight_info = {"uid0": 0.5, "uid1": 0.3, "uid2": 0.2}
    netuid = int(os.getenv("NETUID", "0"))
    priority = 1 if netuid == 296 else 2
    payload = AgoraStatus(id="api", from_server=MINER_WALLET_HOTKEY, priority=priority, description=str(weight_info), status="ok")
    posted = await post_to_agora(payload)
    assert posted, "Failed to post to Agora"


async def test_post_weights_to_agora():
    from scoring.engine import post_weights_to_agora
    hotkey = MINER_WALLET_HOTKEY
    block = 123456
    uids = [0, 1, 2]
    weights = [0.5, 0.3, 0.2]
    status = "ok"
    await post_weights_to_agora(hotkey, block, uids, weights, status)
