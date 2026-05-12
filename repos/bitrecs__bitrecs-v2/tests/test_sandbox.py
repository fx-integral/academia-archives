import os
import secrets
import sqlite3
import uuid
import httpx
import pytest
import logging
import yaml
import pandas as pd
import affinetes as af_env
from models.eval_type import BitrecsEvaluationType
from dotenv import load_dotenv
load_dotenv()


logger = logging.getLogger(__name__)

PARENT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

# @pytest.mark.asyncio
# async def test_calculator_sandbox_example():    
#     try:
#         import docker
#         client = docker.from_env()
#         client.ping()
#     except Exception:
#         pytest.skip("Docker daemon not running, skipping test")
#         logger.warning("Docker daemon not running, skipping test")
    
#     image_tag = af_env.build_image_from_env(
#         env_path=os.path.join(PARENT_DIR, "sandbox/environments/calc"),
#         image_tag="calculator:latest"
#     )
#     logger.info(f"Built Docker image with tag: {image_tag}")    
    
#     env = af_env.load_env(
#         image="calculator:latest",
#         env_vars={"CHUTES_API_KEY": "your-api-key"}, 
#         host_network=True,
#         host_port=8080,
#         log_file="calculator_env.log"
#     )

#     assert env is not None
#     logger.info("Loaded Docker environment successfully")        
    
#     result = await env.evaluate(
#         model="deepseek-ai/DeepSeek-V3",
#         base_url="https://llm.chutes.ai/v1",
#         task_id=10
#     )
#     print(result)  # {"score": 1.0, "success": True}
#     assert result["score"] == 1.0
#     assert result["success"] == True   



async def try_get_run_log(run_id: str) -> str | None:    
    timeout = (10, 60)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"http://localhost:8000/run_log/{run_id}",
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 200:
            log = response.json()
            return log
        else:
            logger.error(f"Failed to get run log for {run_id}: {response.status_code}")
            return None


async def try_get_eval_db(run_id: str) -> str | None:
    timeout = (10, 60)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"http://localhost:8000/db",
            headers={"Content-Type": "application/octet-stream"}
        )
        if response.status_code == 200:
            
            db_path = os.path.join(PARENT_DIR, "data", f"evals_db_{run_id}.sqlite")
            with open(db_path, "wb") as f:
                f.write(response.content)
            logger.info(f"Downloaded evals DB to {db_path}")
            return db_path
        else:
            logger.error(f"Failed to download evals DB: {response.status_code}")
            return None   

    


@pytest.mark.asyncio
async def test_bitrecs_eval_sandbox():     
    af_run_token = os.environ.get("BITRECS_RUN_TOKEN")
    af_run_token = secrets.token_hex(16) if not af_run_token else af_run_token    
    bitrecs_run_id = str(uuid.uuid4())

    af_env_vars = {
            "BITRECS_RUN_TOKEN": af_run_token,
            "BITRECS_RUN_ID": bitrecs_run_id,
            "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY"),
            "CHUTES_API_KEY": os.environ.get("CHUTES_API_KEY")
        }
    assert all(af_env_vars.values()), "Provider API keys must be set in environment variables"

    env = af_env.load_env(
        image="ghcr.io/bitrecs/bitrecs-evals:main",
        env_vars=af_env_vars,
        mode="docker",
        host_network=True,
        cleanup=False,
        force_recreate=True,
        host_port=8000,
        pull=True
    )
    
    assert env is not None
    logger.info("Loaded Docker environment successfully")

    yaml_file_path = os.path.join(PARENT_DIR, "miner", "miner_artifact.yaml")
    with open(yaml_file_path, "r") as f:
        miner_artifact_data = yaml.safe_load(f)

    logger.info(f"Testing model: {miner_artifact_data.get('model', 'N/A')} with provider: {miner_artifact_data.get('provider', 'N/A')}")
    yaml_content = yaml.dump(miner_artifact_data)
    logger.info(f"Loaded YAML content from : {yaml_file_path}")    
    
    timeout = (30, 600)
    data = {"yaml_content": yaml_content, "run_token": af_run_token, "problem_name": "bitrecs_basic_daily"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            "http://localhost:8000/evaluate",
            json=data,
            headers={"Content-Type": "application/json"}
        )
        logger.info(f"Received response: {response.text}")
        #response.raise_for_status()
        result = response.json()    
    
    print("Evaluation Result:")
    print(f"  Task Name: {result.get('task_name', 'N/A')}")
    print(f"  Success: {result.get('success', 'N/A')}")
    print(f"  Run ID: {result.get('run_id', 'N/A')}")
    print(f"  Bitrecs Run ID: {result.get('bitrecs_run_id', 'N/A')}")    
    print(f"  Score: {result.get('score', 'N/A')}")    
    print(f"  Duration: {result.get('duration', 'N/A')}")
    print("  Extra:")
    if 'extra' in result and 'result' in result['extra']:
        print(result['extra']['result'])
    else:
        print("    No extra details available")

    run_id = result.get("run_id")
    logger.info(f"Completed evaluation run with ID: {run_id}")

    log = await try_get_run_log(run_id)
    assert log is not None, "Failed to retrieve run log"
    
    docker_run_id = log["run_id"]
    report = log["report"]
    print(f"Run Log - Docker Run ID: {docker_run_id}")
    print("Run Log - Report:")
    print(report)

    final_score = result.get("score")
    assert final_score is not None, "Final score is missing in the result"
    assert final_score >= 0.0 and final_score <= 1.0, "Final score is out of expected range [0.0, 1.0]"

    sql_db = await try_get_eval_db(bitrecs_run_id)
    assert sql_db is not None, "Failed to download evals DB"
    print(f"Downloaded evals DB to: {sql_db}")
 
    conn = sqlite3.connect(sql_db)
    df = pd.read_sql_query("SELECT eval_name, score, success, rows_evaluated FROM evaluation", conn)
    conn.close()
    
    print("Evals DB - Evaluations Table:")
    print(df.head())

    await env.cleanup()


@pytest.mark.asyncio
async def test_bitrecs_sandbox_contains_valid_eval_types():
    af_run_token = os.environ.get("BITRECS_RUN_TOKEN")
    af_run_token = secrets.token_hex(16) if not af_run_token else af_run_token    
    bitrecs_run_id = str(uuid.uuid4())
    af_hostname = "localhost"
    af_container_port = 8000

    af_env_vars = {
            "BITRECS_RUN_TOKEN": af_run_token,
            "BITRECS_RUN_ID": bitrecs_run_id,
            "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY"),
            "CHUTES_API_KEY": os.environ.get("CHUTES_API_KEY")
        }
    assert all(af_env_vars.values()), "Provider API keys must be set in environment variables"

    env = af_env.load_env(
        image="ghcr.io/bitrecs/bitrecs-evals:main",
        env_vars=af_env_vars,
        mode="docker",
        host_network=True,
        cleanup=False,
        force_recreate=True,
        host_port=af_container_port,
        pull=True
    )
    
    assert env is not None
    logger.info("Loaded Docker environment successfully")

    async def get_evals_from_docker(url: str) -> dict | None:
        """Fetch evals from a Docker container."""
        try:
            timeout = (5, 10)    
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers={"Content-Type": "application/json"})
                response.raise_for_status()
                data = response.json()
                return data
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching evals from Docker: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"Error fetching evals from Docker: {e}")
        return None    
    
   
    evals = await get_evals_from_docker(f"http://{af_hostname}:{af_container_port}/evals")
    assert evals is not None, "Failed to fetch evals from Docker container"
    logger.info(f"Fetched evals from Docker container: {evals}")

    assert "enabled_evaluations" in evals, "Eval data missing 'enabled_evaluations' key"
    enabled_evaluations = evals["enabled_evaluations"]
    for eval in enabled_evaluations:
        logger.info(f"Enabled Evaluation: {eval}")
        try:
            BitrecsEvaluationType(eval)
        except ValueError:
            assert False, f"Unknown evaluation type: {eval}"

    await env.cleanup()



async def test_problem_names_to_types():
    problem_names = [
        "bitrecs_safe_daily",
        "bitrecs_qos_daily",
        "bitrecs_haystack_daily",
        "bitrecs_basic_daily",
        "amazon_all_beauty_100",
        "amazon_beauty_and_personal_care_100",
        "amazon_industrial_and_scientific_100"
    ]
    
    for name in problem_names:
        try:
            eval_type = BitrecsEvaluationType(name)
            logger.info(f"Problem name '{name}' maps to evaluation type: {eval_type}")
        except ValueError:
            assert False, f"Problem name '{name}' does not map to any known evaluation type"