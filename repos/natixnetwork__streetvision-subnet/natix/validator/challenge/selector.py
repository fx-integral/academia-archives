import numpy as np

from natix.validator.config import CHALLENGE_TYPE


def determine_challenge_type(media_cache, synthetic_cache):
    modality = "image"
    label = np.random.choice(list(CHALLENGE_TYPE.keys()))
    source = np.random.choice(["synthetic", "real", "api"])

    if source == "synthetic":
        task = "i2i" if np.random.rand() < 0.5 else "t2i"
        cache = synthetic_cache[modality][task]
    elif source == "real":
        task = "real"
        cache = media_cache["Roadwork"][modality]
    else:  # api
        task = "api"
        cache = None

    return label, modality, task, cache, source
