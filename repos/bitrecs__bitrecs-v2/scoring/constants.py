"""Shared scoring constants."""

# Threshold and statistical constants
MIN_THRESHOLD_GAP: float = 0.02
MAX_THRESHOLD_GAP: float = 0.08
DEFAULT_Z_SCORE: float = 1.5
DEFAULT_EPISODES_PER_ENV: int = 50

# Dominance and epsilon constants
MIN_EPSILON: float = 0.005
MAX_EPSILON: float = 0.05

# Other scoring constants
MINER_EMISSION_PORTION: float = 0.10

# Decay constants for emissions
GRACE_PERIOD_DAYS = 3
DECAY_FACTOR = 0.05  # 5% decay per day after grace period
DECAY_FLOOR = 0.25  # Minimum 25% of emissions after decay