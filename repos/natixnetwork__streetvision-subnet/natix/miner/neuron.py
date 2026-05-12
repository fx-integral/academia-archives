import base64
import io
import typing

import bittensor as bt
from PIL import Image

import natix.miner.detectors
from natix.base.miner import BaseMinerNeuron
from natix.miner.registry import DETECTOR_REGISTRY
from natix.protocol import ImageSynapse
from natix.utils.config import get_device


class Miner(BaseMinerNeuron):

    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        bt.logging.info("Attaching forward function to miner axon.")
        self.axon.attach(
            forward_fn=self.forward_image,
            blacklist_fn=self.blacklist_image,
            priority_fn=self.priority_image,
        )
        bt.logging.info(f"Axon created: {self.axon}")

        bt.logging.info("Loading image detection model if configured")
        self.load_image_detector()

    def load_image_detector(self):
        if (
            str(self.config.neuron.image_detector).lower() == "none"
            or str(self.config.neuron.image_detector_config).lower() == "none"
        ):
            bt.logging.warning("No image detector configuration provided, skipping.")
            self.image_detector = None
            return

        if self.config.neuron.image_detector_device == "auto":
            bt.logging.warning("Automatic device configuration enabled for image detector")
            self.config.neuron.image_detector_device = get_device()

        self.image_detector = DETECTOR_REGISTRY[self.config.neuron.image_detector](
            config_name=self.config.neuron.image_detector_config, device=self.config.neuron.image_detector_device
        )
        bt.logging.info(f"Loaded image detection model: {self.config.neuron.image_detector}")

    async def forward_image(self, synapse: ImageSynapse) -> ImageSynapse:
        if self.image_detector is None:
            bt.logging.info("Image detection model not configured; skipping image challenge")
        else:
            bt.logging.info("Received image challenge!")
            try:
                image_bytes = base64.b64decode(synapse.image)
                image = Image.open(io.BytesIO(image_bytes))
                synapse.prediction = self.image_detector(image)
            except Exception as e:
                bt.logging.error("Error performing inference")
                bt.logging.error(e)

            bt.logging.info(f"PREDICTION = {synapse.prediction}")
            label = synapse.testnet_label
            if synapse.testnet_label != -1:
                bt.logging.info(f"LABEL (testnet only) = {label}")
        return synapse

    async def blacklist_image(self, synapse: ImageSynapse) -> typing.Tuple[bool, str]:
        return await self.blacklist(synapse)

    async def priority_image(self, synapse: ImageSynapse) -> float:
        return await self.priority(synapse)

    def save_state(self):
        pass
