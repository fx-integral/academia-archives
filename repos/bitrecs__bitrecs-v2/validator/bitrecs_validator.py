import os
import sys
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import httpx
import random
import secrets
import asyncio
import traceback
import validator.config as config
import affinetes as af_env
import utils.logger as logger
from dotenv import load_dotenv
load_dotenv()
from uuid import UUID
from typing import Any, Dict
from utils.git import COMMIT_HASH
from utils.system_metrics import get_system_metrics
from models.agent import Agent
from api.endpoints.validator_models import (
    InferenceCostEstimateRequest, ScreenerRegistrationRequest, ScreenerRegistrationResponse, 
    ValidatorDisconnectRequest, ValidatorFinishEvaluationRequest, 
    ValidatorHeartbeatRequest, ValidatorRegistrationRequest, 
    ValidatorRegistrationResponse, ValidatorRequestEvaluationRequest, 
    ValidatorRequestEvaluationResponse, ValidatorUpdateEvaluationRunRequest
)
from models.problem import ProblemTestResult, ProblemTestResultStatus
from models.evaluation_run import EvaluationRunErrorCode, EvaluationRunStatus
from evaluator.models import EvaluationRunException
from models.eval_type import BitrecsEvaluationType
from validator.http_utils import get_bitrecs_platform, post_bitrecs_platform
from scoring.engine import calculate_scores, get_current_eval_set_id
from scoring.persist import ScorePersister
from utils.docker import is_running_in_container, list_all_docker_containers, get_eval_container_sha
from validator.r2_sync import r2_sync
from get_version import get_git_info
from utils.epoch import get_current_epoch_info
from utils.subtensor import get_subtensor
from models.inference_report import InferenceReport


EVAL_TIMEOUT = (30, 600)
RETRY_SLEEP_ON_ERROR = 60
PARENT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
STATE_BACKUP = ScorePersister(base_path="data/weights", filename="scores.db")


async def list_docker_containers_loop():
    while True:
        containers = await list_all_docker_containers()
        logger.info(f"Running Docker containers: {len(containers)}:")
        for container in containers:
            logger.info(f"Container Name: {container['name']}, Image: {container['image']}, Status: {container['status']}, Created: {container['created']}, Id: {container['id']}")
        eval_sha = await get_eval_container_sha()
        logger.info(f"Eval container SHA: {eval_sha}")
        await asyncio.sleep(1800)



async def calculate_scores_loop():
    BLOCKS_BEFORE_EPOCH_TO_SET_WEIGHTS = 30  # ~6 minutes
    last_set_epoch = -1  # Track last epoch weights were set
    logger.info("Starting calculate scores loop")
    logger.info(f"Blocks before epoch to set weights: {BLOCKS_BEFORE_EPOCH_TO_SET_WEIGHTS}")
    
    try:
        await asyncio.sleep(60)
        await asyncio.wait_for(
            calculate_scores(netuid=config.NETUID, validator_hotkey=config.VALIDATOR_HOTKEY, set_weights=False),
            timeout=120
        )
    except Exception as e:
        logger.warning(f"Initial score calculation failed (non-fatal): {e}")

    while True:
        try:
            logger.debug("Calculate scores loop iteration starting...")
            await asyncio.sleep(config.SET_WEIGHTS_INTERVAL_SECONDS)  # 300s
            logger.info("----WEIGHT UPDATE CHECK----")
            
            # Try to get subtensor - sometimes custom endpoints down
            try:
                st = await get_subtensor()
            except Exception as e:
                logger.error(f"Failed to get subtensor connection: {e}. Skipping weight check this iteration.")
                continue  # Skip to next loop iteration
            
            # Proceed with weight logic
            current_block = await st.get_current_block()
            current_epoch, blocks_until_next_epoch, epoch_start_block = get_current_epoch_info(current_block, config.NETUID)
            
            duration_m = blocks_until_next_epoch * 12 / 60
            logger.info(f"Current block: {current_block}, current epoch: {current_epoch}, epoch start block: {epoch_start_block}")
            logger.info(f"Blocks until next epoch: {blocks_until_next_epoch} (~{duration_m:.1f} minutes)")
            
            should_set_weights = blocks_until_next_epoch <= BLOCKS_BEFORE_EPOCH_TO_SET_WEIGHTS and current_epoch != last_set_epoch
            if should_set_weights:
                logger.info(f"\033[32mWithin {BLOCKS_BEFORE_EPOCH_TO_SET_WEIGHTS} blocks of epoch - setting weights\033[0m")
                result = await asyncio.wait_for(
                    calculate_scores(netuid=config.NETUID, validator_hotkey=config.VALIDATOR_HOTKEY, set_weights=should_set_weights),
                    timeout=120
                )
                if result:
                    last_set_epoch = current_epoch
                    logger.info(f"\033[32mWeights set for epoch ending at block ~{epoch_start_block + blocks_until_next_epoch}\033[0m")
                else:
                    logger.warning("\033[31mWeight set attempted but failed — will retry next loop\033[0m")
            else:
                logger.info("Not near epoch flip or already set this epoch - skipped")
        
        except asyncio.TimeoutError as e:
            logger.error(f"asyncio.TimeoutError in calculate_scores(): {e}")
        except Exception as e:
            logger.error(f"Unexpected error in calculate_scores_loop(): {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            # Continue the loop even on unexpected errors


async def send_heartbeat_loop():
    logger.info("Starting send heartbeat loop...")
    while True:
        asyncio.create_task(send_heartbeat_once())  # Fire-and-forget task
        await asyncio.sleep(config.SEND_HEARTBEAT_INTERVAL_SECONDS)


async def send_heartbeat_once():
    try:
        branch, sha = get_git_info()
        logger.info(f"Sending heartbeat... Branch: {branch}, SHA: {sha}")
        system_metrics = await get_system_metrics()
        await post_bitrecs_platform("/validator/heartbeat", ValidatorHeartbeatRequest(system_metrics=system_metrics), bearer_token=session_id, quiet=2)
    except Exception as e:
        logger.error(f"Error sending heartbeat: {type(e).__name__}: {e}")
        # Log and continue; don't exit


async def r2_sync_loop():
    try:
        logger.info("Starting R2 sync loop...")
        while True:
            await r2_sync()
            await asyncio.sleep(config.R2_SYNC_INTERVAL_SECONDS)
    except Exception as e:
        logger.error(f"Error in r2_sync_loop(): {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        os._exit(1)


async def get_health_from_docker(url: str) -> dict | None:    
    try:
        async with httpx.AsyncClient(timeout=(10, 60)) as client:
            response = await client.get(url, headers={"Content-Type": "application/json"})            
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Health check HTTP error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
    return None


async def get_run_log_from_docker(run_id: str, port: int, hostname: str) -> str | None:    
    try:
        async with httpx.AsyncClient(timeout=(10, 60)) as client:
            url =  f"http://{hostname}:{port}/run_log/{run_id}"
            response = await client.get(url, headers={"Content-Type": "application/json"})
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get run log for {run_id}: {response.status_code}")
                return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching run log from Docker: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logger.error(f"Error fetching run log from Docker: {e}")
    return None   


async def get_eval_log(run_id: str) -> str | None:
    log_path = os.path.join(PARENT_DIR, "logs", f"eval_{run_id}.log")
    if not os.path.exists(log_path):
        logger.error(f"Eval log file not found: {log_path}")
        return None
    try:
        with open(log_path, "r") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading eval log file {log_path}: {e}")
        return None


async def get_cost_estimate(provider: str, model: str, input_tokens: int, output_tokens: int) -> Dict[str, Any] | None:
    try:
        response = await post_bitrecs_platform("/inference/estimate-cost", 
                                            InferenceCostEstimateRequest(
                                                provider=provider, 
                                                model_name=model,
                                                input_tokens=input_tokens,
                                                output_tokens=output_tokens),
                                                bearer_token=session_id, quiet=2)
        if response is not None and "input_cost" in response and "output_cost" in response:
            return response
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching cost estimate: {e.response.status_code} - {e.response.text}")
        return None

async def post_cost_report(evaluation_run_id: UUID,
                           provider: str, model: str, 
                           temperature: float, 
                           messages: list, 
                           status_code: int, 
                           response: str, 
                           num_input_tokens: int, 
                           num_output_tokens: int, 
                           cost_usd: float):
    try:
        await post_bitrecs_platform("/inference/report-cost", 
                                    InferenceReport(
                                        evaluation_run_id=evaluation_run_id,
                                        provider=provider,
                                        model=model,
                                        temperature=temperature,
                                        messages=messages,
                                        status_code=status_code,
                                        response=response,
                                        num_input_tokens=num_input_tokens,
                                        num_output_tokens=num_output_tokens,
                                        cost_usd=cost_usd,
                                        response_sent_at=int(time.time())
                                    ),
                                    bearer_token=session_id, quiet=2)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error reporting inference cost: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logger.error(f"Error reporting inference cost: {e}")


async def load_agent_by_evaluation_run(evaluation_run_id: UUID) -> Agent:
    """Load an agent by its evaluation run ID."""
    response = await get_bitrecs_platform(f"/agent/get-by-evaluation-run-id?evaluation_run_id={evaluation_run_id}", quiet=2)
    agent = Agent(**response)
    return agent


async def update_evaluation_run(evaluation_run_id: UUID, problem_name: str, updated_status: EvaluationRunStatus, extra: Dict[str, Any] = {}):
    logger.info(f"Updating evaluation run {evaluation_run_id} for problem {problem_name} to {updated_status.value}...")    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            await post_bitrecs_platform("/validator/update-evaluation-run", ValidatorUpdateEvaluationRunRequest(
                evaluation_run_id=evaluation_run_id,
                updated_status=updated_status,
                **(extra or {})
            ), bearer_token=session_id, quiet=2)
            return  # Success, exit
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401 and attempt < max_retries - 1:
                logger.warning(f"Session expired (401) on attempt {attempt + 1}. Re-registering and retrying...")
                await register_validator()
                continue  # Retry with new session
            else:
                raise  # Re-raise if not 401 or max retries hit


async def _simulate_run_evaluation_run(evaluation_run_id: UUID, problem_name: str):
    logger.info(f"Starting simulated evaluation run {evaluation_run_id} for problem {problem_name}...")

    SIMULATE_EVALUATION_RUN_MAX_TIME_PER_STAGE_SECONDS = random.choice([1, 3, 4])
    # Move from pending -> initializing_agent
    await asyncio.sleep(random.random() * SIMULATE_EVALUATION_RUN_MAX_TIME_PER_STAGE_SECONDS)
    await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.initializing_agent)

    # Move from initializing_agent -> running_agent
    await asyncio.sleep(random.random() * SIMULATE_EVALUATION_RUN_MAX_TIME_PER_STAGE_SECONDS)
    await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.running_agent)

    # Move from running_agent -> initializing_eval
    await asyncio.sleep(random.random() * SIMULATE_EVALUATION_RUN_MAX_TIME_PER_STAGE_SECONDS)
    await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.initializing_eval, {
        "patch": "FAKE PATCH",
        "agent_logs": "FAKE AGENT LOGS"
    })

    # Move from initializing_eval -> running_eval
    await asyncio.sleep(random.random() * SIMULATE_EVALUATION_RUN_MAX_TIME_PER_STAGE_SECONDS)
    await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.running_eval)

    # Move from running_eval -> finished
    await asyncio.sleep(random.random() * SIMULATE_EVALUATION_RUN_MAX_TIME_PER_STAGE_SECONDS)
    await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.finished, {
        "test_results": [{"name": "fake_test", "category": "default", "status": f"{ProblemTestResultStatus.PASS.value}"}],
        "eval_logs": "FAKE EVAL LOGS"
    })
    
    logger.info(f"Finished simulated evaluation run {evaluation_run_id} for problem {problem_name}")


async def _run_evaluation_run(evaluation_run_id: UUID, problem_name: str, agent_code: str):
    try:
        is_docker = is_running_in_container()
        logger.info(f"Running in container: {is_docker}")
        eval_type = BitrecsEvaluationType(problem_name)
        sleeps = [2, 3, 5]
        sleep = secrets.choice(sleeps)
        logger.info(f"Sleeping for {sleep} seconds before {eval_type.value} ...")
        await asyncio.sleep(sleep)

        try:
            miner_agent = await load_agent_by_evaluation_run(evaluation_run_id)
            if miner_agent is None:
                raise Exception(f"Miner Artifact not found for evaluation run {evaluation_run_id}")            
            evaluation_set_id = await get_current_eval_set_id()
            logger.info("Loaded miner input YAML file successfully")
            logger.info(f"Evaluation set ID: {evaluation_set_id}")
            logger.info(f"Miner Artifact ID: {miner_agent.agent_id}")
            logger.info(f"Miner Artifact Name: {miner_agent.name}")
            logger.info(f"Miner Artifact Status: {miner_agent.status}")
            logger.info(f"Miner Artifact Hotkey: {miner_agent.miner_hotkey}")

            logger.info(f"Testing model: {miner_agent.model} with provider: {miner_agent.provider}")
            cost_estimate = await get_cost_estimate(miner_agent.provider, miner_agent.model, input_tokens=1_000_000, output_tokens=1_000_000)
            if not cost_estimate:
                logger.warning(f"Cost estimate not available for provider: {miner_agent.provider}, model: {miner_agent.model}")
                #raise Exception(f"Cost estimate not available for provider: {miner_agent.provider}, model: {miner_agent.model}")
            else:
                logger.info(f"Cost estimate:  input cost: {cost_estimate['input_cost']}, output cost: {cost_estimate['output_cost']})")

            # Move from pending -> initializing_agent
            await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.initializing_agent)
            
            # Move from initializing_agent -> running_agent
            await asyncio.sleep(random.random() * config.SIMULATE_EVALUATION_RUN_MAX_TIME_PER_STAGE_SECONDS)
            await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.running_agent)

            # Start initializing the agent sandbox
            openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
            chutes_api_key = os.environ.get("CHUTES_API_KEY")
            if not any([openrouter_api_key, chutes_api_key]):
                raise Exception("Missing required API keys for Affine ENV evaluation run")

            bitrecs_run_id = str(evaluation_run_id)            
            af_image = config.EVAL_CONTAINER_TAG
            af_mode = "docker"
            af_hostname = "localhost" if not is_docker else "bitrecs-evals-main"  # Container name for network access
            af_container_port = 8000
            
            af_run_token = secrets.token_hex(16)
            af_env_vars = {                
                "BITRECS_RUN_TOKEN": af_run_token,
                "BITRECS_RUN_ID": bitrecs_run_id,
                "OPENROUTER_API_KEY": openrouter_api_key,
                "CHUTES_API_KEY": chutes_api_key,
                "MODEL_COST_INPUT": str(cost_estimate["input_cost"]),
                "MODEL_COST_OUTPUT": str(cost_estimate["output_cost"])
            }
            env = af_env.load_env(
                image=af_image,
                mode=af_mode,
                env_vars=af_env_vars,                
                host_network=None,
                cleanup=False,
                force_recreate=True,                
                pull=True,
                network="bitrecs-network"
            )
            if env is None:
                raise Exception("Failed to load Docker environment")
            logger.info("Loaded Docker environment successfully")

            docker_log_path = f"logs/eval_{bitrecs_run_id}.log"            
            env.start_logging(docker_log_path)
            
            af_health = await get_health_from_docker(f"http://{af_hostname}:{af_container_port}/health")
            if af_health is None:
                raise Exception("Failed to get heartbeat from Docker environment")
            if af_health["status"] != "healthy":
                raise Exception(f"Docker environment is not healthy: {af_health}")
        
            yaml_content = Agent.to_yaml(miner_agent)
            logger.info(f"Loaded YAML content from : {miner_agent.agent_id}")
            logger.info("Triggering evaluation in Affine environment...")

            # Move from running_agent -> initializing_eval            
            await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.initializing_eval, {
                "patch": "initializing_eval",
                "agent_logs": f"run_id: {bitrecs_run_id}\nDocker container port: {af_container_port}\nDocker environment health: {af_health}"
            })

            await asyncio.sleep(random.random() * 2)
            await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.running_eval)     

            run_data = {"yaml_content": yaml_content, 
                        "run_token": af_run_token,
                        "problem_name": eval_type.value}
            
            logger.info(f"Run timeout set to: {EVAL_TIMEOUT[1]} seconds")
            logger.info(f"\033[32mRunning: {eval_type.value} evaluation... \033[0m")

            async with httpx.AsyncClient(timeout=EVAL_TIMEOUT) as client:
                response = await client.post(
                    f"http://{af_hostname}:{af_container_port}/evaluate",
                    json=run_data,
                    headers={"Content-Type": "application/json"}
                )
                logger.info(f"Received response: {response.text}")
                response.raise_for_status()
                result = response.json()
            
            tak_name = result.get("task_name", "N/A")
            run_id = result.get("run_id", "N/A")
            score = result.get("score", 0.0)
            success = result.get("success", False)
            duration = result.get("duration", 0.0)
            samples = result.get("samples", 0)
            inference_report = result.get("inference_data", {})
            cost_report = result.get("cost_report", {})

            extra = ""
            logger.info("Evaluation Result:")
            logger.info(f"  Run ID: {run_id}")
            logger.info(f"  Task Name: \033[32m{tak_name}\033[0m")
            logger.info(f"  Problem Name: \033[32m{problem_name}\033[0m")
            logger.info(f"  Eval Type: \033[32m{eval_type.value}\033[0m")            
            logger.info(f"\033[32m  Score: {score} \033[0m")
            logger.info(f"  Success: {success}")
            logger.info(f"  Duration: {duration} seconds")
            logger.info("  Extra:")
            if 'extra' in result and 'result' in result['extra']:                
                extra = result['extra']['result']
                logger.info(f"    {extra}")
            else:
                logger.info("    No extra details available")   
            
            this_log = "No logs available"
            run_log = await get_run_log_from_docker(run_id, af_container_port, af_hostname)
            if run_log is None:
                logger.error("Failed to retrieve run log")
            elif "error" in run_log:
                logger.error(f"Error in run log: {run_log['error']}")
                this_log = f"Run Log Error: {run_log['error']}"
            else:
                this_log = run_log["report"] if run_log and "report" in run_log else "No report available"     

            eval_log = await get_eval_log(bitrecs_run_id)
            if eval_log is None:
                logger.error("Failed to retrieve eval log")
                this_log += f"\n\nEval Log Error: Failed to retrieve eval log"
            else:
                this_log += "\n\nEval Log:\n" + (eval_log if eval_log else "No eval log available")

            # if inference_report is not None:
            #     this_log += "\n\nInference Report:\n" + str(inference_report)
            
            await env.cleanup()

            eval_status = ProblemTestResultStatus.PASS if success else ProblemTestResultStatus.FAIL
            eval_score = float(score) if isinstance(score, (int, float)) else 0.0
            problem_test_result = ProblemTestResult(
                name=tak_name,
                category="default",
                status=eval_status,
                score=eval_score,
                duration=duration
            )

            saved = STATE_BACKUP.save_result(uid=miner_agent.miner_uid, 
                                     hotkey=miner_agent.miner_hotkey, 
                                     score=eval_score, 
                                     run_id=str(evaluation_run_id), 
                                     task_name=tak_name, 
                                     success=success, 
                                     duration=duration,
                                     evaluation_set_id=evaluation_set_id,
                                     sample_size=samples)
            if not saved:
                logger.error("Failed to save result to local backup")
            else:
                logger.info("Saved result to local backup successfully")

            total_cost = 0.0
            updated_cost = await get_cost_estimate(miner_agent.provider, 
                                             miner_agent.model, 
                                             input_tokens=cost_report.get("input_tokens", 0), 
                                             output_tokens=cost_report.get("output_tokens", 0))
            if updated_cost:
                logger.info(f"Updated cost estimate: input: {updated_cost['input_cost']}, output: {updated_cost['output_cost']})")
                try:
                    total_cost = float(updated_cost.get("total_cost", 0.0))
                    logger.info(f"Total cost estimate: {total_cost}")
                except (ValueError, TypeError):
                    total_cost = 0.0

            await post_cost_report(
                evaluation_run_id=evaluation_run_id,
                provider=miner_agent.provider,
                model=miner_agent.model,
                temperature=miner_agent.sampling_params.temperature if miner_agent.sampling_params else 0.0,
                messages=[],
                status_code=200 if success else 500,
                response="",
                num_input_tokens=cost_report.get("input_tokens", 0),
                num_output_tokens=cost_report.get("output_tokens", 0),
                cost_usd=total_cost
            )

            await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.finished, {
                "test_results": [problem_test_result.model_dump()],
                "eval_logs": this_log
            })
        except EvaluationRunException as e:
            logger.error(f"Evaluation run {evaluation_run_id} for problem {problem_name} errored: {e}")
            await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.error, {
                "error_code": e.error_code.value,
                "error_message": e.error_message
            })

        except Exception as e:
            logger.error(f"Evaluation run {evaluation_run_id} for problem {problem_name} errored: {EvaluationRunErrorCode.VALIDATOR_INTERNAL_ERROR.get_error_message()}: {e}")
            logger.error(traceback.format_exc())
            await update_evaluation_run(evaluation_run_id, problem_name, EvaluationRunStatus.error, {
                "error_code": EvaluationRunErrorCode.VALIDATOR_INTERNAL_ERROR.value,
                "error_message": f"{EvaluationRunErrorCode.VALIDATOR_INTERNAL_ERROR.get_error_message()}: {e}\n\nTraceback:\n{traceback.format_exc()}"
            })

        logger.info(f"Finished evaluation run {evaluation_run_id} for problem {problem_name}")

    except Exception as e:
        logger.error(f"Error in _run_evaluation_run(): {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        os._exit(1)
    

async def _run_evaluation(request_evaluation_response: ValidatorRequestEvaluationResponse):
    logger.info("Received evaluation:")
    logger.info(f"  # of evaluation runs: {len(request_evaluation_response.evaluation_runs)}")

    SIMULATE_EVALUATION_RUNS = False
    logger.info(f"Starting evaluation...simulating: {SIMULATE_EVALUATION_RUNS}")

    for evaluation_run in request_evaluation_response.evaluation_runs:
        evaluation_run_id = evaluation_run.evaluation_run_id
        problem_name = evaluation_run.problem_name
        logger.info(f"Starting evaluation run {evaluation_run_id} for problem {problem_name}...")      
        if SIMULATE_EVALUATION_RUNS:
            await _simulate_run_evaluation_run(evaluation_run_id, problem_name)            
        else:
            await _run_evaluation_run(evaluation_run_id, problem_name, request_evaluation_response.agent_code)
       
    try:
        await post_bitrecs_platform("/validator/finish-evaluation", ValidatorFinishEvaluationRequest(), bearer_token=session_id, quiet=1)
        if SIMULATE_EVALUATION_RUNS:
            logger.info("\033[33mFinished SIMULATED evaluation\033[0m")
        else:
            logger.info("\033[33mEVALUATION COMPLETE\033[0m")      

    except Exception as e:
        logger.error(f"Error finishing evaluation: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        await disconnect(f"Error finishing evaluation: {type(e).__name__}: {e}")


async def disconnect(reason: str):
    if session_id is None:
        return    
    try:
        logger.info("Disconnecting validator...")
        await post_bitrecs_platform("/validator/disconnect", ValidatorDisconnectRequest(reason=reason), bearer_token=session_id)
        logger.info("Disconnected validator")
    except Exception as e:
        logger.error(f"Error in disconnect(): {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        os._exit(1)


async def register_validator():
    global session_id, running_agent_timeout_seconds, running_eval_timeout_seconds, max_evaluation_run_log_size_bytes
    max_registration_retries = 10
    registration_retry_delay = 60
    
    for attempt in range(max_registration_retries):
        try:
            logger.info(f"Registering validator... (attempt {attempt + 1}/{max_registration_retries})")
            
            if config.MODE == "validator":
                timestamp = int(time.time())
                signed_timestamp = config.VALIDATOR_HOTKEY.sign(str(timestamp)).hex()
                register_response = ValidatorRegistrationResponse(**(await post_bitrecs_platform("/validator/register-as-validator", ValidatorRegistrationRequest(
                    timestamp=timestamp,
                    signed_timestamp=signed_timestamp,
                    hotkey=config.VALIDATOR_HOTKEY.ss58_address,
                    commit_hash=COMMIT_HASH
                ))))
            elif config.MODE == "screener":
                register_response = ScreenerRegistrationResponse(**(await post_bitrecs_platform("/validator/register-as-screener", ScreenerRegistrationRequest(
                    name=config.SCREENER_NAME,
                    password=config.SCREENER_PASSWORD,
                    commit_hash=COMMIT_HASH
                ))))
            
            session_id = register_response.session_id
            running_agent_timeout_seconds = register_response.running_agent_timeout_seconds
            running_eval_timeout_seconds = register_response.running_eval_timeout_seconds
            max_evaluation_run_log_size_bytes = register_response.max_evaluation_run_log_size_bytes
            
            logger.info("Registered validator:")
            logger.info(f"  Session ID: {session_id}")
            logger.info(f"  Running Agent Timeout: {running_agent_timeout_seconds} second(s)")
            logger.info(f"  Running Evaluation Timeout: {running_eval_timeout_seconds} second(s)")
            logger.info(f"  Max Evaluation Run Log Size: {max_evaluation_run_log_size_bytes} byte(s)")
            
            break
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                logger.warning(f"Registration failed with 409 Conflict (attempt {attempt + 1}): {e.response.text}")
                if attempt < max_registration_retries - 1:
                    logger.info(f"Retrying registration in {registration_retry_delay} seconds...")
                    await asyncio.sleep(registration_retry_delay)
                else:
                    logger.error("Max registration retries reached. Exiting.")
                    raise         
            else:
                raise
        except Exception as e:
            logger.error(f"Registration failed (attempt {attempt + 1}): {type(e).__name__}: {e}")
            if attempt < max_registration_retries - 1:
                logger.info(f"Retrying registration in {registration_retry_delay} seconds...")
                await asyncio.sleep(registration_retry_delay)
            else:
                logger.error("Max registration retries reached. Exiting.")
                raise


async def main():
    global session_id
    global running_agent_timeout_seconds
    global running_eval_timeout_seconds
    global max_evaluation_run_log_size_bytes 

    asyncio.create_task(list_docker_containers_loop())
    
    await register_validator()
    
    asyncio.create_task(send_heartbeat_loop())
    
    node_name = config.VALIDATOR_HOTKEY.ss58_address[:8] if config.MODE == "validator" else config.SCREENER_NAME
    if config.MODE == "validator":
        asyncio.create_task(calculate_scores_loop())
        asyncio.create_task(r2_sync_loop())
    
    # Loop forever, just keep requesting evaluations and running them
    while True:
        try:
            logger.info(f"{node_name}: Requesting an evaluation...")
            request_evaluation_response_data = await post_bitrecs_platform("/validator/request-evaluation", ValidatorRequestEvaluationRequest(), bearer_token=session_id, quiet=1)            
            if request_evaluation_response_data is None:
                logger.info(f"No evaluations available. Waiting for {config.REQUEST_EVALUATION_INTERVAL_SECONDS} seconds...")
                await asyncio.sleep(config.REQUEST_EVALUATION_INTERVAL_SECONDS)
                continue
            
            logger.info(f"Received evaluation with {request_evaluation_response_data}")
            await _run_evaluation(ValidatorRequestEvaluationResponse(**request_evaluation_response_data))

            if config.MODE == "validator":
                await calculate_scores(netuid=config.NETUID, validator_hotkey=config.VALIDATOR_HOTKEY, set_weights=False)
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.warning("Session expired (401). Re-registering...")
                await register_validator()
                continue  # Skip sleep and retry immediately with new session
            else:
                raise  # Re-raise for other HTTP errors
        except Exception as e:
            logger.error(f"Error running evaluation: {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(RETRY_SLEEP_ON_ERROR)
 


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt")
        asyncio.run(disconnect("Keyboard interrupt"))
        os._exit(1)
    except Exception as e:
        logger.error(f"Error in main(): {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        asyncio.run(disconnect(f"Error in main(): {type(e).__name__}: {e}"))
        os._exit(1)
