import asyncio
import base64
import os
import unittest

import numpy as np
from PIL import Image

from natix.protocol import ImageSynapse
from natix.miner.neuron import Miner


SAMPLE_IMAGE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_image.jpg")


class TestMiner(unittest.TestCase):

    def setUp(self):
        self.miner = Miner.__new__(Miner)
        self.miner.config = self.miner.config()

        with open(SAMPLE_IMAGE, "rb") as img_file:
            self.image = Image.open(SAMPLE_IMAGE)
            self.image_bytes = img_file.read()
            self.image_base64 = base64.b64encode(self.image_bytes).decode("utf-8")

    def test_init_detector(self):
        self.miner.load_image_detector()
        self.assertIsNotNone(self.miner.image_detector, "Detector should not be None")

    def test_image_detector(self):
        self.miner.load_image_detector()
        prediction = self.miner.image_detector(self.image)
        self.assertIsNotNone(prediction, "Prediction should not be None")
        self.assertIsInstance(prediction, (float, np.ndarray))
        self.assertTrue(0 <= float(prediction) <= 1)

    def test_forward_synapse(self):
        self.miner.load_image_detector()
        synapse = ImageSynapse(image=self.image_base64)
        pred = asyncio.run(self.miner.forward_image(synapse)).prediction
        self.assertIsNotNone(pred)
        self.assertIsInstance(pred, float)
        self.assertTrue(0 <= pred <= 1)


if __name__ == "__main__":
    unittest.main()
