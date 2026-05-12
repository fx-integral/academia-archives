import os
import utils.logger as logger
from dotenv import load_dotenv
load_dotenv()

ENV = os.getenv("ENV")
if not ENV:
    logger.fatal("ENV is not set in .env")

if ENV != "prod" and ENV != "dev":
    logger.fatal("ENV must be either 'prod' or 'dev'")

NETUID = os.getenv("NETUID")
if not NETUID:
    logger.fatal("NETUID is not set in .env")
NETUID = int(NETUID)

SUBTENSOR_ADDRESS = os.getenv("SUBTENSOR_ADDRESS")
if not SUBTENSOR_ADDRESS:
    logger.warning("SUBTENSOR_ADDRESS is not set in .env")

SUBTENSOR_NETWORK = os.getenv("SUBTENSOR_NETWORK")
if not SUBTENSOR_NETWORK:
    logger.fatal("SUBTENSOR_NETWORK is not set in .env")

BURN = os.getenv("BURN")
if not BURN:
    logger.fatal("BURN is not set in .env")
BURN = BURN.lower() == "true"

DISALLOW_UPLOADS = os.getenv("DISALLOW_UPLOADS")
if not DISALLOW_UPLOADS:
    logger.fatal("DISALLOW_UPLOADS is not set in .env")
DISALLOW_UPLOADS = DISALLOW_UPLOADS.lower() == "true"

if DISALLOW_UPLOADS:
    DISALLOW_UPLOADS_REASON = os.getenv("DISALLOW_UPLOADS_REASON", "System Maintenanence - Artifact submissions are temporarily disabled")
    if not DISALLOW_UPLOADS_REASON:
        logger.fatal("DISALLOW_UPLOADS_REASON is not set in .env")

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
if not R2_ACCESS_KEY_ID:
    logger.fatal("R2_ACCESS_KEY_ID is not set in .env")
    
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
if not R2_SECRET_ACCESS_KEY:
    logger.fatal("R2_SECRET_ACCESS_KEY is not set in .env")


R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
if not R2_BUCKET_NAME:
    logger.fatal("R2_BUCKET_NAME is not set in .env")

R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
if not R2_ENDPOINT_URL:
    logger.fatal("R2_ENDPOINT_URL is not set in .env")

DATABASE_USERNAME = os.getenv("DATABASE_USERNAME")
if not DATABASE_USERNAME:
    logger.fatal("DATABASE_USERNAME is not set in .env")
    
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
if not DATABASE_PASSWORD:
    logger.fatal("DATABASE_PASSWORD is not set in .env")
    
DATABASE_HOST = os.getenv("DATABASE_HOST")
if not DATABASE_HOST:
    logger.fatal("DATABASE_HOST is not set in .env")
    
DATABASE_PORT = os.getenv("DATABASE_PORT")
if not DATABASE_PORT:
    logger.fatal("DATABASE_PORT is not set in .env")
DATABASE_PORT = int(DATABASE_PORT)
    
DATABASE_NAME = os.getenv("DATABASE_NAME")
if not DATABASE_NAME:
    logger.fatal("DATABASE_NAME is not set in .env")

SCREENER_PASSWORD = os.getenv("SCREENER_PASSWORD")
if not SCREENER_PASSWORD:
    logger.fatal("SCREENER_PASSWORD is not set in .env")

SCREENER_1_THRESHOLD = os.getenv("SCREENER_1_THRESHOLD")
if not SCREENER_1_THRESHOLD:
    logger.fatal("SCREENER_1_THRESHOLD is not set in .env")
SCREENER_1_THRESHOLD = float(SCREENER_1_THRESHOLD)

SCREENER_2_THRESHOLD = os.getenv("SCREENER_2_THRESHOLD")
if not SCREENER_2_THRESHOLD:
    logger.fatal("SCREENER_2_THRESHOLD is not set in .env")
SCREENER_2_THRESHOLD = float(SCREENER_2_THRESHOLD)

PRUNE_THRESHOLD = os.getenv("PRUNE_THRESHOLD")
if not PRUNE_THRESHOLD:
    logger.fatal("PRUNE_THRESHOLD is not set in .env")
PRUNE_THRESHOLD = float(PRUNE_THRESHOLD)

VALIDATOR_HEARTBEAT_TIMEOUT_SECONDS = os.getenv("VALIDATOR_HEARTBEAT_TIMEOUT_SECONDS")
if not VALIDATOR_HEARTBEAT_TIMEOUT_SECONDS:
    logger.fatal("VALIDATOR_HEARTBEAT_TIMEOUT_SECONDS is not set in .env")
VALIDATOR_HEARTBEAT_TIMEOUT_SECONDS = int(VALIDATOR_HEARTBEAT_TIMEOUT_SECONDS)

VALIDATOR_HEARTBEAT_TIMEOUT_INTERVAL_SECONDS = os.getenv("VALIDATOR_HEARTBEAT_TIMEOUT_INTERVAL_SECONDS")
if not VALIDATOR_HEARTBEAT_TIMEOUT_INTERVAL_SECONDS:
    logger.fatal("VALIDATOR_HEARTBEAT_TIMEOUT_INTERVAL_SECONDS is not set in .env")
VALIDATOR_HEARTBEAT_TIMEOUT_INTERVAL_SECONDS = int(VALIDATOR_HEARTBEAT_TIMEOUT_INTERVAL_SECONDS)

VALIDATOR_SET_BUILDER_LOOP_INTERVAL_SECONDS = 30

VALIDATOR_RUNNING_AGENT_TIMEOUT_SECONDS = os.getenv("VALIDATOR_RUNNING_AGENT_TIMEOUT_SECONDS")
if not VALIDATOR_RUNNING_AGENT_TIMEOUT_SECONDS:
    logger.fatal("VALIDATOR_RUNNING_AGENT_TIMEOUT_SECONDS is not set in .env")
VALIDATOR_RUNNING_AGENT_TIMEOUT_SECONDS = int(VALIDATOR_RUNNING_AGENT_TIMEOUT_SECONDS)

VALIDATOR_RUNNING_EVAL_TIMEOUT_SECONDS = os.getenv("VALIDATOR_RUNNING_EVAL_TIMEOUT_SECONDS")
if not VALIDATOR_RUNNING_EVAL_TIMEOUT_SECONDS:
    logger.fatal("VALIDATOR_RUNNING_EVAL_TIMEOUT_SECONDS is not set in .env")
VALIDATOR_RUNNING_EVAL_TIMEOUT_SECONDS = int(VALIDATOR_RUNNING_EVAL_TIMEOUT_SECONDS)

VALIDATOR_MAX_EVALUATION_RUN_LOG_SIZE_BYTES = os.getenv("VALIDATOR_MAX_EVALUATION_RUN_LOG_SIZE_BYTES")
if not VALIDATOR_MAX_EVALUATION_RUN_LOG_SIZE_BYTES:
    logger.fatal("VALIDATOR_MAX_EVALUATION_RUN_LOG_SIZE_BYTES is not set in .env")
VALIDATOR_MAX_EVALUATION_RUN_LOG_SIZE_BYTES = int(VALIDATOR_MAX_EVALUATION_RUN_LOG_SIZE_BYTES)


NUM_EVALS_PER_AGENT = os.getenv("NUM_EVALS_PER_AGENT")
if not NUM_EVALS_PER_AGENT:
    logger.fatal("NUM_EVALS_PER_AGENT is not set in .env")
NUM_EVALS_PER_AGENT = int(NUM_EVALS_PER_AGENT)

EVALUATION_CEILING_MULTIPLIER = 3
MAX_TOTAL_EVALS_PER_AGENT = int(os.getenv("MAX_TOTAL_EVALS_PER_AGENT", str(NUM_EVALS_PER_AGENT * EVALUATION_CEILING_MULTIPLIER)))

ARTIFACTS_PER_INTERVAL = int(os.getenv("ARTIFACTS_PER_INTERVAL", 50))

MAX_SCREENER_2_ATTEMPTS = int(os.getenv("MAX_SCREENER_2_ATTEMPTS", "3"))

logger.info("=== API Configuration ===")
logger.info("-------------------------")
logger.info(f"Network ID: {NETUID}")
logger.info(f"Subtensor Address: {SUBTENSOR_ADDRESS}")
logger.info(f"Subtensor Network: {SUBTENSOR_NETWORK}")
logger.info("-------------------------")
if BURN:
    logger.warning("Burning!")
    logger.info("-------------------------")

if DISALLOW_UPLOADS:
    logger.warning(f"Disallowing Uploads: {DISALLOW_UPLOADS_REASON}")
    logger.info("-------------------------")

logger.info(f"Environment: {'Production' if ENV == 'prod' else 'Development'}")
logger.info("-------------------------")

logger.info(f"R2 Bucket Name: {R2_BUCKET_NAME}")
logger.info("-------------------------")

logger.info(f"Database Name: {DATABASE_NAME}")
logger.info("-------------------------")

logger.info(f"Screener 1 Threshold: {SCREENER_1_THRESHOLD}")
logger.info(f"Screener 2 Threshold: {SCREENER_2_THRESHOLD}")
logger.info(f"Prune Threshold: {PRUNE_THRESHOLD}")
logger.info("-------------------------")

logger.info(f"Validator Heartbeat Timeout: {VALIDATOR_HEARTBEAT_TIMEOUT_SECONDS} second(s)")
logger.info(f"Validator Heartbeat Timeout Interval: {VALIDATOR_HEARTBEAT_TIMEOUT_INTERVAL_SECONDS} second(s)")
logger.info(f"Validator Evaluation Set Loop Interval: {VALIDATOR_SET_BUILDER_LOOP_INTERVAL_SECONDS} second(s)")
logger.info("-------------------------")

logger.info(f"Validator Running Agent Timeout: {VALIDATOR_RUNNING_AGENT_TIMEOUT_SECONDS} second(s)")
logger.info(f"Validator Running Evaluation Timeout: {VALIDATOR_RUNNING_EVAL_TIMEOUT_SECONDS} second(s)")
logger.info(f"Validator Max Evaluation Run Log Size: {VALIDATOR_MAX_EVALUATION_RUN_LOG_SIZE_BYTES} byte(s)")
logger.info("-------------------------")


logger.info(f"Number of Evaluations per Agent: {NUM_EVALS_PER_AGENT}")
logger.info(f"Max Total Evaluations per Agent: {MAX_TOTAL_EVALS_PER_AGENT}")
logger.info(f"Max Screener 2 Attempts: {MAX_SCREENER_2_ATTEMPTS}")
logger.info("-------------------------")
logger.info(f"Evaluation Ceiling Multiplier: {EVALUATION_CEILING_MULTIPLIER}")
logger.info(f"Artifacts per Interval: {ARTIFACTS_PER_INTERVAL}")

logger.info("=========================")