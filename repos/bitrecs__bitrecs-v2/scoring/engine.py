import os
import time
import httpx
import asyncio
import pandas as pd
import utils.logger as logger
from bittensor import NeuronInfo
from bittensor_wallet import Keypair, Wallet
from utils.subtensor import close_subtensor, get_subtensor
from scoring.pareto import compute_pareto_frontier
from scoring.threshold import compute_miner_thresholds
from scoring.types import MinerFirstBlocks, MinerScores
from scoring.wta import compute_subset_scores_with_priority, scores_to_weights
from queries.evaluation_set import get_latest_set_id
from scoring.constants import MINER_EMISSION_PORTION, GRACE_PERIOD_DAYS, DECAY_FACTOR, DECAY_FLOOR


def calculate_decay_factor(first_block: int, current_block: int, block_time_seconds: int = 12) -> float:  
    if first_block <= 0 or first_block >= current_block:
        return 1.0
    
    time_elapsed_seconds = (current_block - first_block) * block_time_seconds
    grace_period_seconds = GRACE_PERIOD_DAYS * 24 * 3600
    
    if time_elapsed_seconds <= grace_period_seconds:
        return 1.0
    
    days_past_grace = (time_elapsed_seconds - grace_period_seconds) / (24 * 3600)
    decay_factor = max(DECAY_FLOOR, 1.0 - DECAY_FACTOR * days_past_grace)
    return decay_factor


async def get_current_eval_set_id() -> int:
    try:
        return await get_latest_set_id()
    except Exception as e:
        SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "")    
        if not SERVICE_URL:
            SERVICE_URL = "http://localhost:8000"        
        headers = {"Content-Type": "application/json", 
                   "X-API-Key": os.environ.get("BITRECS_PLATFORM_API_KEY")}
        client = httpx.Client(base_url=SERVICE_URL, headers=headers)
        response = client.get("/scoring/latest-set-info")
        data = response.json()
        return data["latest_set_id"]
    

def df_to_miner_scores(df) -> MinerScores:
    """
    Aggregate scores: take the max per hotkey+task (to handle retries by using the best score).
    """
    miner_scores: MinerScores = {}    
    grouped = df.groupby(['hotkey', 'task_name']).agg({'score': 'max', 'uid': 'first'}).reset_index()
    for _, row in grouped.iterrows():
        uid = row['uid']
        env_id = row['task_name']
        score = row['score']
        if uid not in miner_scores:
            miner_scores[uid] = {}
        miner_scores[uid][env_id] = score    
    logger.info(f"Aggregated scores: {len(grouped)} hotkey+task combinations (max per group)")
    return miner_scores


def df_to_samples(df) -> dict[str, int]:
    """
    Get sample size per task
    """
    samples = {}    
    grouped = df.groupby('task_name')['sample_size'].max().reset_index()
    for _, row in grouped.iterrows():
        samples[row['task_name']] = row['sample_size']
    return samples


def miners_first_blocks() -> MinerFirstBlocks:
    SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "http://localhost:8000")
    headers = {"Content-Type": "application/json", 
            "X-API-Key": os.environ.get("BITRECS_PLATFORM_API_KEY")}
    client = httpx.Client(base_url=SERVICE_URL, headers=headers)
    response = client.get("/retrieval/miner-blocks")
    assert response.status_code == 200
    data = response.json()
    return data
    

def df_to_miner_blocks(df) -> MinerFirstBlocks:
    miner_blocks = miners_first_blocks()    
    hotkey_to_uid = {}
    for _, row in df.iterrows():
        hotkey = row['hotkey']
        uid = row['uid']
        hotkey_to_uid[hotkey] = uid
    miner_first_blocks: MinerFirstBlocks = {}
    for hotkey, block in miner_blocks.items():
        uid = hotkey_to_uid.get(hotkey)
        if uid is not None:
            miner_first_blocks[uid] = block
    return miner_first_blocks


def latest_scores_to_df() -> pd.DataFrame:
    SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "http://localhost:8000")  
    headers = {"Content-Type": "application/json", 
            "X-API-Key": os.environ.get("BITRECS_PLATFORM_API_KEY")}
    client = httpx.Client(base_url=SERVICE_URL, headers=headers)
    response = client.get("/scoring/latest")
    assert response.status_code == 200
    data = response.json()
    df = pd.DataFrame(data["scores"])
    return df


async def calculate_scores(netuid: int, validator_hotkey: Keypair, set_weights: bool = False) -> bool:
    try:
        logger.info("Calculating scores...")       
        current_set_id = await get_current_eval_set_id()
        logger.info(f"Current evaluation set ID: {current_set_id}")
        if set_weights and MINER_EMISSION_PORTION <= 0:
            return await set_weights_burn_only(current_set_id, validator_hotkey, netuid)

        data = latest_scores_to_df()
        logger.info(f"Loaded {len(data)} score records")
        if data.empty:
            logger.warning(f"\033[33mNo score data available to process for evaluation set {current_set_id}\033[0m")
            return False
        
        logger.info("Calculating miner scores and weights...")
        miner_scores = df_to_miner_scores(data)
        samples = df_to_samples(data)
        envs = list(samples.keys())
        miner_blocks = df_to_miner_blocks(data)
        miner_thresholds = compute_miner_thresholds(miner_scores, episodes_per_env=samples)

        pareto_result = compute_pareto_frontier(miner_scores, envs, samples)
        frontier_uids = set(pareto_result.frontier_uids)
        filtered_scores = {uid: s for uid, s in miner_scores.items() if uid in frontier_uids}
        
        subset_scores = compute_subset_scores_with_priority(filtered_scores, miner_thresholds, miner_blocks, envs)
        weights = scores_to_weights(subset_scores)
        logger.info("Subset scores:")
        for uid, score in sorted(subset_scores.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  UID {uid}: {score:.1f} points")

        logger.info("Final weights:")
        for uid, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  UID {uid}: {weight:.4f}")
        
        weight_receiving_uid = max(weights, key=weights.get)
        first_block = miner_blocks.get(weight_receiving_uid, 0)
        if first_block == 0:
            logger.warning(f"\033[33mNo block information for UID {weight_receiving_uid}. Cannot set weights on chain.\033[0m")
            return False
        if set_weights:            
            result = await set_weights_onchain(current_set_id, validator_hotkey, netuid, weight_receiving_uid, first_block)
            if result:
                logger.info(f"\033[32mWeights set successfully on chain for UID {weight_receiving_uid}\033[0m")
                return True
            else:
                logger.error(f"\033[31mFailed to set weights on chain for UID {weight_receiving_uid}\033[0m")
                return False            
        else:
            logger.info(f"\033[33mWeight candidate with highest score: {weight_receiving_uid}\033[0m")
            logger.info("\033[33mWeights not set on chain (set_weights=False)\033[0m")
            return False
    except asyncio.TimeoutError as te:
        logger.error(f"TimeoutError in calculate_scores: {te}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False
    except Exception as e:
        logger.error(f"Exception in calculate_scores: {e}")
        import traceback
        traceback_str = traceback.format_exc()        
        logger.error(f"Full traceback: {traceback_str}")        
        raise


async def set_weights_burn_only(eval_set_id: int, validator_hotkey: Keypair, netuid: int) -> bool:
    st = time.perf_counter()
    logger.info("--- Begin Set Weights (Burn Only) ---")
    wallet = Wallet(name=os.getenv("VALIDATOR_WALLET_NAME"), hotkey=os.getenv("VALIDATOR_HOTKEY_NAME"))
    if wallet.hotkey.ss58_address != validator_hotkey.ss58_address:
        logger.error(f"Validator hotkey mismatch: expected {wallet.hotkey.ss58_address}, got {validator_hotkey.ss58_address}")
        return False
    subtensor = await get_subtensor()
    current_block = await subtensor.get_current_block()
    
    uids = [0]
    weights = [1.0]
    try:
        success = await subtensor.set_weights(
            wallet=wallet,
            netuid=netuid,
            uids=uids,
            weights=weights,
            wait_for_inclusion=True,
            wait_for_finalization=True,
        )
        await post_weight_set(
            netuid=netuid,
            block=current_block,
            validator_hotkey=wallet.hotkey.ss58_address,
            wta_uid=0,
            wta_hotkey="burn",
            wta_weight=1.0,
            weights={0: 1.0},
            evaluation_set_id=eval_set_id
        )        
        await post_weights_to_agora(wallet.hotkey.ss58_address, 
                                    current_block, uids, weights, 
                                    "ok" if success else "error")
        if success:
            logger.info("✅ Burn-only weights set successfully (chain confirmed)")
            return True
        else:
            logger.error("❌ Chain rejected burn-only weight setting")
            return False
    except Exception as e:
        logger.error(f"Error in set_weights_burn_only: {e}")
        return False
    finally:
        await close_subtensor()
        et = time.perf_counter() - st
        logger.info(f"Total time for set_weights_burn_only: {et:.4f} seconds")
        logger.info("--- End Set Weights (Burn Only) ---")


async def set_weights_onchain(eval_set_id: int, validator_hotkey: Keypair, netuid: int, weight_receiving_uid: int, first_block: int) -> bool:
    st = time.perf_counter()
    logger.info("--- Begin Set Weights ---")
    wallet = Wallet(name=os.getenv("VALIDATOR_WALLET_NAME"), hotkey=os.getenv("VALIDATOR_HOTKEY_NAME"))
    if wallet.hotkey.ss58_address != validator_hotkey.ss58_address:
        logger.error(f"Validator hotkey mismatch: expected {wallet.hotkey.ss58_address}, got {validator_hotkey.ss58_address}")
        return False
    subtensor = await get_subtensor()
    neuron_info : NeuronInfo = await subtensor.neuron_for_uid(uid=weight_receiving_uid, netuid=netuid)
    if not neuron_info:
        logger.error(f"Could not find neuron info for UID {weight_receiving_uid} on netuid {netuid}")
        return False
    last_update = neuron_info.last_update
    miner_hotkey = neuron_info.hotkey
    is_registered = await subtensor.is_hotkey_registered(hotkey_ss58=miner_hotkey, netuid=netuid)
    if not is_registered:
        logger.error(f"Miner hotkey {miner_hotkey} is not registered on netuid {netuid}")
        return False
    
    current_block = await subtensor.get_current_block()
    decay_factor = calculate_decay_factor(first_block, current_block)
    logger.info(f"Decay factor for UID {weight_receiving_uid}: {decay_factor:.4f} (first block: {first_block}, current block: {current_block})")
    miner_weight = MINER_EMISSION_PORTION * decay_factor
    burn_weight = 1 - miner_weight
    if not (0 <= miner_weight <= 1):
        logger.error(f"Invalid weights: miner_weight={miner_weight}, burn_weight={burn_weight}. Must be >=0, <=1, and sum to 1.")
        return False
    
    uids = [0, weight_receiving_uid]
    weights = [burn_weight, miner_weight]
    try:
        max_retries = 3
        timeout = 90.0
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempt {attempt + 1}/{max_retries}")
                success = await asyncio.wait_for(
                    subtensor.set_weights(
                        wallet=wallet,
                        netuid=netuid,
                        uids=uids,
                        weights=weights,
                        wait_for_inclusion=True,
                        wait_for_finalization=True,
                    ),
                    timeout=timeout
                )
                await post_weight_set(
                    netuid=netuid,
                    block=current_block,
                    validator_hotkey=wallet.hotkey.ss58_address,
                    wta_uid=weight_receiving_uid,
                    wta_hotkey=miner_hotkey,
                    wta_weight=miner_weight,
                    weights={uid: weight for uid, weight in zip(uids, weights)},
                    evaluation_set_id=eval_set_id
                )

                await post_weights_to_agora(wallet.hotkey.ss58_address, 
                                            current_block, uids, weights, 
                                            "ok" if success else "error")
                if success:
                    logger.info("✅ Weights set successfully (chain confirmed)")
                    return True
                else:
                    logger.error(f"❌ Chain rejected weight setting on attempt {attempt + 1}")
            except asyncio.TimeoutError:
                logger.error(f"Timeout on attempt {attempt + 1}")
            except Exception as e:
                logger.error(f"Error on attempt {attempt + 1}: {e}")
            
            if attempt < max_retries - 1:
                logger.info("Retrying in 60 seconds...")
                await asyncio.sleep(60)
            else:
                logger.error("❌ All attempts failed")
                return False
        
        return False
    
    finally:
        await close_subtensor()
        et = time.perf_counter() - st
        logger.info(f"Total time for set_weights_onchain: {et:.4f} seconds")
        logger.info("--- End Set Weights ---")


async def post_weights_to_agora(hotkey: str, block: int, uids: list[int], weights: list[float], status: str) -> None:    
    try:
        from utils.agora import post_to_agora, AgoraStatus
        weight_info = {f"uid{uid}": weight for uid, weight in zip(uids, weights)}
        mode = os.getenv("MODE", "unknown_mode")
        netuid = int(os.getenv("NETUID", "0"))
        priority = 1 if netuid == 122 else 2
        id = f"{mode}_{netuid}"
        payload = AgoraStatus(
            id=id,
            from_server=hotkey,
            priority=priority,
            description=str({"block": block, "weights": weight_info}),
            status=status
        )
        await post_to_agora(payload)
    except Exception as e:
        logger.error(f"post_weights_to_agora failed to post weights to Agora: {e}")


async def post_weight_set(
    netuid: int,
    block: int,
    validator_hotkey: str,
    wta_uid: int,
    wta_hotkey: str,
    wta_weight: float,
    weights: dict[int, float],
    evaluation_set_id: int
) -> bool:
    try:
        SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "http://localhost:8000")
        async with httpx.AsyncClient(base_url=SERVICE_URL) as client:
            headers = {
                'Accept': 'application/json',
                'X-API-Key': os.getenv("BITRECS_PLATFORM_API_KEY")
            }        
            payload = {
                "netuid": netuid,
                "block": block,
                "validator_hotkey": validator_hotkey,
                "wta_uid": wta_uid,
                "wta_hotkey": wta_hotkey,
                "wta_weight": wta_weight,
                "weights": str(weights),
                "evaluation_set_id": evaluation_set_id
            }            
            response = await client.post("/scoring/weight-set", json=payload, headers=headers)
            response.raise_for_status()
            logger.info(f"Post weight set sucess: {payload}")
            return True
    except Exception as e:
        logger.error(f"Failed to post weight set: {e}")
        return False