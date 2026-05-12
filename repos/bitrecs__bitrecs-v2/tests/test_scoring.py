import os
import json
import httpx
import pytest
import typer
import utils.logger as logger
from pathlib import Path
from scoring.constants import DEFAULT_Z_SCORE, MAX_THRESHOLD_GAP, MIN_THRESHOLD_GAP
from scoring.engine import df_to_miner_blocks, df_to_miner_scores, df_to_samples, get_current_eval_set_id, latest_scores_to_df, miners_first_blocks
from scoring.pareto import compute_pareto_frontier
from scoring.persist import ScorePersister
from scoring.threshold import compute_miner_thresholds
from scoring.wta import compute_subset_scores_with_priority, scores_to_weights
root_path = Path(__file__).parent.parent.absolute()

DATA_FILE_PATH = os.path.join(root_path, "data", "weights")
#DATA_FILE = "scores.db"
#DATA_FILE = "combined_20260331_132851.sqlite"
DATA_FILE = "combined_20260401_095652.sqlite"


@pytest.mark.asyncio
async def test_latest_eval_set_id():
    set_id = await get_current_eval_set_id()
    assert isinstance(set_id, int)
    assert set_id > 0


def test_pareto_frontier():
    miner_scores = {
        1: {"env1": 0.8, "env2": 0.6},
        2: {"env1": 0.7, "env2": 0.7},
        3: {"env1": 0.9, "env2": 0.5},
        4: {"env1": 0.6, "env2": 0.8},
    }
    env_ids = ["env1", "env2"]
    n_samples_per_env = {"env1": 1, "env2": 1}
    
    pareto_result = compute_pareto_frontier(miner_scores, env_ids=env_ids, n_samples_per_env=n_samples_per_env)

    assert set(pareto_result.frontier_uids) == {1, 2, 3, 4}
    assert pareto_result.dominance_matrix.shape == (4, 4)
    assert pareto_result.score_matrix.shape == (4, 2)
    assert pareto_result.uid_mapping == [1, 2, 3, 4]


def test_miner_first_blocks():
    miner_blocks = miners_first_blocks()
    print(f"Miner first blocks: {miner_blocks}")
    assert isinstance(miner_blocks, dict)
    for hotkey, block in miner_blocks.items():
        assert isinstance(hotkey, str)
        assert isinstance(block, int)
        assert block >= 0


@pytest.mark.asyncio
async def test_pareto_frontier_from_db():    
    current_set_id = await get_current_eval_set_id()
    print(f"Current evaluation_set_id: {current_set_id}")
    
    persister = ScorePersister(base_path=DATA_FILE_PATH, filename=DATA_FILE)
    print(f"{persister.file_path}")    
    if not os.path.exists(persister.file_path):
        raise FileNotFoundError(f"Database file not found at {persister.file_path}")
    
    data = persister.load_scores(evaluation_set_id=current_set_id)   
    if data.empty or len(data) == 0:
        raise ValueError(f"No score data found for evaluation_set_id {current_set_id}")

    miner_scores = df_to_miner_scores(data)
    samples = df_to_samples(data)    
    envs = list(samples.keys())    
    
    pareto_result = compute_pareto_frontier(miner_scores=miner_scores, env_ids=envs, n_samples_per_env=samples)    
    
    print("Pareto Frontier Properties:")
    print(f"  Frontier UIDs: {pareto_result.frontier_uids}")
    print(f"  UID Mapping: {pareto_result.uid_mapping}")
    print(f"  Dominance Matrix Shape: {pareto_result.dominance_matrix.shape}")
    print(f"  Score Matrix Shape: {pareto_result.score_matrix.shape}")
    print(f"  Dominance Matrix:\n{pareto_result.dominance_matrix}")
    print(f"  Score Matrix:\n{pareto_result.score_matrix}")    
    
    import pandas as pd
    score_df = pd.DataFrame(pareto_result.score_matrix, columns=envs, index=pareto_result.uid_mapping)
    print(f"  Score DataFrame:\n{score_df}")
    
    assert len(pareto_result.frontier_uids) > 0

@pytest.mark.asyncio
async def test_pareto_frontier_api():
    SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "")
    #SERVICE_URL = "http://localhost:8000"
    async with httpx.AsyncClient(base_url=SERVICE_URL) as client:
        headers = {
            'Accept': 'application/json',
            'X-API-Key': os.getenv("BITRECS_PLATFORM_API_KEY")
        }
        response = await client.get("/scoring/pareto", headers=headers)
        assert response.status_code == 200
        data = response.json()
        pretty = json.dumps(data, indent=2) 
        print(f"{pretty}")        
        assert "frontier_uids" in data
        assert "dominance_matrix" in data
        assert "score_matrix" in data
        assert "uid_mapping" in data


@pytest.mark.asyncio
async def test_wta_api():
    SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "")
    #SERVICE_URL = "http://localhost:8000"
    async with httpx.AsyncClient(base_url=SERVICE_URL) as client:
        headers = {
            'Accept': 'application/json',
            'X-API-Key': os.getenv("BITRECS_PLATFORM_API_KEY")
        }
        response = await client.get("/scoring/wta", headers=headers)
        assert response.status_code == 200
        data = response.json()
        pretty = json.dumps(data, indent=2) 
        print(f"{pretty}")
        assert "subset_scores" in data
        assert "weights" in data


@pytest.mark.asyncio
async def test_scoring_wta():
    current_set_id = await get_current_eval_set_id()
    print(f"Current evaluation_set_id: {current_set_id}")
    persister = ScorePersister(base_path=DATA_FILE_PATH, filename=DATA_FILE)
    data = persister.load_scores(evaluation_set_id=current_set_id)
    print(f"Loaded {len(data)} score records")
    miner_scores = df_to_miner_scores(data)
    samples = df_to_samples(data)
    envs = list(samples.keys())
    miner_blocks = df_to_miner_blocks(data)
    miner_thresholds = compute_miner_thresholds(miner_scores, episodes_per_env=samples,
                                                z_score=DEFAULT_Z_SCORE,
                                                min_gap=MIN_THRESHOLD_GAP,
                                                max_gap=MAX_THRESHOLD_GAP)

    pareto_result = compute_pareto_frontier(miner_scores, envs, samples)
    frontier_uids = set(pareto_result.frontier_uids)
    filtered_scores = {uid: s for uid, s in miner_scores.items() if uid in frontier_uids}

    subset_scores = compute_subset_scores_with_priority(
        filtered_scores, miner_thresholds, miner_blocks, envs
    )
    weights = scores_to_weights(subset_scores)
    typer.echo("\nSubset scores:")
    for uid, score in sorted(subset_scores.items(), key=lambda x: x[1], reverse=True):
        typer.echo(f"  UID {uid}: {score:.1f} points")

    typer.echo("\nFinal weights:")
    for uid, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        typer.echo(f"  UID {uid}: {weight:.4f}")

    top_weight_uid = max(weights, key=weights.get)
    typer.echo(f"\nTop weight UID: {top_weight_uid} with weight {weights[top_weight_uid]:.4f}")



@pytest.mark.asyncio
async def test_scoring_wta_global():
    current_set_id = await get_current_eval_set_id()
    print(f"Current evaluation_set_id: {current_set_id}")  
    data = latest_scores_to_df()
    print(f"Loaded {len(data)} score records")
    miner_scores = df_to_miner_scores(data)
    samples = df_to_samples(data)
    envs = list(samples.keys())
    miner_blocks = df_to_miner_blocks(data)
    miner_thresholds = compute_miner_thresholds(miner_scores, episodes_per_env=samples,
                                                z_score=DEFAULT_Z_SCORE,
                                                min_gap=MIN_THRESHOLD_GAP,
                                                max_gap=MAX_THRESHOLD_GAP)

    pareto_result = compute_pareto_frontier(miner_scores, envs, samples)
    frontier_uids = set(pareto_result.frontier_uids)
    filtered_scores = {uid: s for uid, s in miner_scores.items() if uid in frontier_uids}

    subset_scores = compute_subset_scores_with_priority(
        filtered_scores, miner_thresholds, miner_blocks, envs
    )
    weights = scores_to_weights(subset_scores)
    typer.echo("\nSubset scores:")
    for uid, score in sorted(subset_scores.items(), key=lambda x: x[1], reverse=True):
        typer.echo(f"  UID {uid}: {score:.1f} points")

    typer.echo("\nFinal weights:")
    for uid, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        typer.echo(f"  UID {uid}: {weight:.4f}")

    top_weight_uid = max(weights, key=weights.get)
    typer.echo(f"\nTop weight UID: {top_weight_uid} with weight {weights[top_weight_uid]:.4f}")



@pytest.mark.asyncio
async def test_scoring_wta_all():    
    current_set_id = await get_current_eval_set_id()
    print(f"Current evaluation_set_id: {current_set_id}")    
    dbs = ["5Eyj7B2PzUMzRpW59eXziw4LazsQkn8bESF5gnbchyTdZEhX_scores.sqlite", 
           "5FNL6e4JsB3ZPUGk1x1izK1xnTWsZDZrVF6WaRp1gNpoTvsM_scores.sqlite", 
           "5FtH6Aj3xKbkNdgbZUghkTeJrkJexn6eBRZSnS8Zgc3oo4GX_scores.sqlite"]

    for db in dbs:
        print(f"\nTesting with database: {db}")
        persister = ScorePersister(base_path=DATA_FILE_PATH, filename=db)
        data = persister.load_scores(evaluation_set_id=current_set_id)
        print(f"Loaded {len(data)} score records")
        miner_scores = df_to_miner_scores(data)
        samples = df_to_samples(data)
        envs = list(samples.keys())
        miner_blocks = df_to_miner_blocks(data)   
        miner_thresholds = compute_miner_thresholds(miner_scores, episodes_per_env=samples)

        pareto_result = compute_pareto_frontier(miner_scores, envs, samples)
        frontier_uids = set(pareto_result.frontier_uids)
        filtered_scores = {uid: s for uid, s in miner_scores.items() if uid in frontier_uids}

        subset_scores = compute_subset_scores_with_priority(
            filtered_scores, miner_thresholds, miner_blocks, envs
        )
        weights = scores_to_weights(subset_scores)
        typer.echo("\nSubset scores:")
        for uid, score in sorted(subset_scores.items(), key=lambda x: x[1], reverse=True):
            typer.echo(f"  UID {uid}: {score:.1f} points")

        typer.echo("\nFinal weights:")
        for uid, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            typer.echo(f"  UID {uid}: {weight:.4f}")

        top_weight_uid = max(weights, key=weights.get)
        typer.echo(f"\nTop weight UID: {top_weight_uid} with weight {weights[top_weight_uid]:.4f}")


@pytest.mark.asyncio
async def test_get_latest_scores():    
    #SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "")
    SERVICE_URL = "http://localhost:8000"
    async with httpx.AsyncClient(base_url=SERVICE_URL) as client:
        headers = {
            'Accept': 'application/json',
            'X-API-Key': os.getenv("BITRECS_PLATFORM_API_KEY")
        }
        response = await client.get("/scoring/latest", headers=headers)
        assert response.status_code == 200
        data = response.json()
        pretty = json.dumps(data, indent=2) 
        print(f"{pretty}")
        assert "scores" in data        



@pytest.mark.asyncio
async def test_post_weight_set():    
        netuid = 100
        block = 123456
        validator_hotkey = "5FNL6e4JsB3ZPUGk1x1izK1xnTWsZDZrVF6WaRp1gNpoTvsM"
        wta_uid = 42
        wta_hotkey = "5FtH6Aj3xKbkNdgbZUghkTeJrkJexn6eBRZSnS8Zgc3oo4GX"
        wta_weight = 0.75
        weights = {0: 0.25, 42: 0.75}
        evaluation_set_id = 7
    
        result = await post_weight_set(
            netuid=netuid,
            block=block,
            validator_hotkey=validator_hotkey,
            wta_uid=wta_uid,
            wta_hotkey=wta_hotkey,
            wta_weight=wta_weight,
            weights=weights,
            evaluation_set_id=evaluation_set_id
        )
        assert result, "Failed to post weight set to platform"



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
        SERVICE_URL = "http://localhost:8000"
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
            logger.info(f"Posting weight set to platform: {payload}")        
            response = await client.post("/scoring/weight-set", json=payload, headers=headers)
            response.raise_for_status()
            logger.info(f"Successfully posted to Agora: {payload}")
            return True
    except Exception as e:
        logger.error(f"Failed to post to Agora: {e}")
        return False