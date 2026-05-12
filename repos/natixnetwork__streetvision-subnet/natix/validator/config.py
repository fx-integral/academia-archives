from pathlib import Path
from typing import Dict, List

from natix.constants import TARGET_IMAGE_SIZE  # re-exported; canonical source is natix/constants.py

MAINNET_UID = 72
TESTNET_UID = 323

MAINNET_WANDB_PROJECT = "natix-subnet"
TESTNET_WANDB_PROJECT = "natix-testnet"
HUGGINGFACE_REPO = "natix-network-org"
WANDB_ENTITY = "natix_network_org"

HUGGINGFACE_CACHE_DIR: Path = Path.home() / ".cache" / "huggingface"
NATIX_CACHE_DIR: Path = Path.home() / ".cache" / "natix"
NATIX_CACHE_DIR.mkdir(parents=True, exist_ok=True)

VALIDATOR_INFO_PATH: Path = NATIX_CACHE_DIR / "validator.yaml"

ROADWORK_CACHE_DIR: Path = NATIX_CACHE_DIR / "Roadwork"
SYNTH_CACHE_DIR: Path = NATIX_CACHE_DIR / "Synthetic"
ROADWORK_IMAGE_CACHE_DIR: Path = ROADWORK_CACHE_DIR / "image"

T2V_CACHE_DIR: Path = SYNTH_CACHE_DIR / "t2v"
T2I_CACHE_DIR: Path = SYNTH_CACHE_DIR / "t2i"
I2I_CACHE_DIR: Path = SYNTH_CACHE_DIR / "i2i"

IMAGE_PARQUET_CACHE_UPDATE_INTERVAL = 2  # hours
IMAGE_CACHE_UPDATE_INTERVAL = 1          # hours

MAX_COMPRESSED_GB = 100
MAX_EXTRACTED_GB = 10

CHALLENGE_TYPE = {0: "None", 1: "Roadwork"}

REWARD_CURVE_EXPONENT = 3.0  # >1.0 steepens the reward curve

MAX_TASKS_PER_DAY = 1440
ORGANIC_TASK_RATIO = 0.10

IMAGE_DATASETS: Dict[str, List[Dict[str, str]]] = {
    "Roadwork": [
        {"path": f"{HUGGINGFACE_REPO}/roadwork"},
    ],
}
