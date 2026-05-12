# Subnet Hyperparameters
TEMPO = 360  # Number of blocks per epoch

# Results Settings
EPOCH_RESULTS_DIR = "epoch_results"
MAX_EPOCH_FILES = 48

# Recovery State Files
STATE_FILE = ".merit_state.json"
HEALTH_FILE = ".merit_health.json"

# Ping Settings
PING_TIMEOUT = 10         # Timeout per ping attempt (seconds)
PING_RETRY_ATTEMPTS = 2   # Number of retries if ping fails
PING_RETRY_DELAY = 0.5    # Delay (in seconds) between retries
