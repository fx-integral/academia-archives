import math
from common import settings as common_settings


def calculate_n_partitions(n_miners: int, n_splits: int) -> int:
    """Calculate the number of partitions for a given number of miners.

    Args:
        n_miners (int): The number of miners.

    Returns:
        int: The number of partitions.
    """
    return (n_miners // n_splits) * 2


def calculate_num_parts(data: bytes) -> int:
    """Calculate the number of parts to upload a file to S3.

    Args:
        data (bytes): The data to upload.

    Returns:
        int: The number of parts to upload.
    """
    return int(math.ceil(len(data) / common_settings.MAX_PART_SIZE))
