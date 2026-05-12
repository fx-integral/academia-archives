from enum import Enum
from typing import NewType, TypeAlias

MinerUID = NewType("MinerUID", int)
BlockNumber = NewType("BlockNumber", int)
EnvironmentId = NewType("EnvironmentId", str)
Seed = NewType("Seed", int)

MinerScores: TypeAlias = dict[MinerUID, dict[EnvironmentId, float]]  # uid -> env_id -> score
MinerThresholds: TypeAlias = dict[MinerUID, dict[EnvironmentId, float]]  # uid -> env_id -> threshold
MinerFirstBlocks: TypeAlias = dict[MinerUID, BlockNumber]  # uid -> block_number


class SubsetWeightScheme(Enum):    
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    EQUAL = "equal"