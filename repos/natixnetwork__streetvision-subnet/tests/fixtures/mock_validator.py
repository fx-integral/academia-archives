import bittensor as bt
import numpy as np
from PIL import Image

from natix.utils.mock import MockDendrite, MockMetagraph, MockSubtensor, create_random_image
from natix.validator.scoring.performance_tracker import MinerPerformanceTracker


class MockImageDataset:
    def __init__(self, huggingface_dataset_path, huggingface_datset_split="train",
                 huggingface_datset_name=None, create_splits=False, download_mode=None):
        self.huggingface_dataset_path = huggingface_dataset_path
        self.huggingface_dataset_name = huggingface_datset_name
        self.dataset = ""
        self.sampled_images_idx = []

    def __getitem__(self, index):
        return {"image": create_random_image(), "id": index, "source": self.huggingface_dataset_path}

    def __len__(self):
        return 100

    def sample(self, k=1):
        return [self.__getitem__(i) for i in range(k)], list(range(k))


class MockSyntheticDataGenerator:
    def __init__(self, prompt_type, use_random_t2v_model, t2v_model_name):
        self.prompt_type = prompt_type
        self.t2v_model_name = t2v_model_name
        self.use_random_t2v_model = use_random_t2v_model

    def generate(self, k=1, real_images=None, modality="image"):
        return [{"prompt": f"mock {self.prompt_type} prompt", "image": create_random_image(), "id": i} for i in range(k)]


class MockValidator:
    def __init__(self, config):
        self.config = config
        subtensor = MockSubtensor(config.netuid, wallet=bt.MockWallet())

        self.performance_trackers = {"image": MinerPerformanceTracker()}
        self.metagraph = MockMetagraph(netuid=config.netuid, subtensor=subtensor)
        self.dendrite = MockDendrite(bt.MockWallet())
        self.scores = np.zeros(self.metagraph.n, dtype=np.float32)
        self._fake_prob = config.fake_prob

        self.roadwork_media_cache = {"image": _MockImageCache()}
        self.synthetic_media_cache = {"image": {"t2i": _MockImageCache(), "i2i": _MockImageCache()}}
        self.media_cache = {"Roadwork": self.roadwork_media_cache}

        from natix.utils.uids import UIDDeck
        self.uid_deck = UIDDeck()

    def update_scores(self, rewards, miner_uids):
        pass

    def save_miner_history(self):
        pass


class _MockImageCache:
    """Minimal cache stub that returns a random image on sample()."""
    def sample(self, label=None, remove_from_cache=False):
        return {"image": create_random_image(), "path": "mock", "dataset": "mock",
                "index": 0, "mask_center": None, "metadata": {"label": label or 0}}

    def _prune_extracted_cache(self):
        pass
