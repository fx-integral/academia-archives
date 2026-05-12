import os
import time

import bittensor as bt

from natix.base.validator import BaseValidatorNeuron
from natix.validator.cache import ImageCache
from natix.validator.config import (
    I2I_CACHE_DIR,
    ROADWORK_IMAGE_CACHE_DIR,
    T2I_CACHE_DIR,
)
from natix.validator.forward import forward
from natix.validator.monitoring import cleanup_wandb, init_wandb, store_vali_info
from natix.validator.proxy import ValidatorProxy
from natix.utils.uids import UIDDeck

os.environ["CUDA_VISIBLE_DEVICES"] = ""


class Validator(BaseValidatorNeuron):

    def __init__(self, config=None):
        super().__init__(config=config)

        self.uid_deck = UIDDeck()
        self.organic_uid_deck = UIDDeck()
        self.last_responding_miner_uids = []

        self.validator_proxy = ValidatorProxy(self)

        self.roadwork_media_cache = {"image": ImageCache(ROADWORK_IMAGE_CACHE_DIR)}
        self.synthetic_media_cache = {"image": {"t2i": ImageCache(T2I_CACHE_DIR), "i2i": ImageCache(I2I_CACHE_DIR)}}
        self.media_cache = {"Roadwork": self.roadwork_media_cache}

        self.wandb_run = None
        self.wandb_restart_timer = None
        init_wandb(self)
        store_vali_info(self)

        self._fake_prob = self.config.get("fake_prob", 0.5)

    async def forward(self):
        return await forward(self)

    def __exit__(self, exc_type, exc_value, traceback):
        cleanup_wandb(self)
        super().__exit__(exc_type, exc_value, traceback)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    with Validator() as validator:
        while True:
            bt.logging.info(
                f"Validator | UID:{validator.uid} | "
                f"Stake:{validator.metagraph.S[validator.uid]:.3f} | "
                f"VTrust:{validator.metagraph.Tv[validator.uid]:.3f} | "
                f"Dividend:{validator.metagraph.D[validator.uid]:.3f} | "
                f"Emission:{validator.metagraph.E[validator.uid]:.3f}"
            )
            time.sleep(30)
