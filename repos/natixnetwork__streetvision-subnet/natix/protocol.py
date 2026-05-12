# The MIT License (MIT)
# Copyright © 2025 Natix

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import base64
from io import BytesIO

import bittensor as bt
import pydantic
from PIL import Image


def prepare_synapse(input_data, modality):
    # torch tensors are only produced by the synthetic generation path (validator-synthetic extra).
    # Import lazily so this module is importable without torch installed.
    try:
        import torch
        from torchvision import transforms as tv_transforms
        if isinstance(input_data, torch.Tensor):
            input_data = tv_transforms.ToPILImage()(input_data.cpu().detach())
        if isinstance(input_data, list) and isinstance(input_data[0], torch.Tensor):
            for i, img in enumerate(input_data):
                input_data[i] = tv_transforms.ToPILImage()(img.cpu().detach())
    except ImportError:
        pass

    if modality == "image":
        return prepare_image_synapse(input_data)
    elif modality == "video":
        bt.logging.error("Video synapse not implemented yet")
    else:
        raise NotImplementedError(f"Unsupported modality: {modality}")


def prepare_image_synapse(image: Image.Image) -> "ImageSynapse":
    image_bytes = BytesIO()
    image.save(image_bytes, format="JPEG")
    b64_encoded_image = base64.b64encode(image_bytes.getvalue())
    return ImageSynapse(image=b64_encoded_image)


class ImageSynapse(bt.Synapse):
    """
    Wire format between miner and validator.

    The validator sends a base64-encoded JPEG; the miner returns a float prediction:
      > 0.5  — image is AI-generated/modified
      <= 0.5 — image is real
    """

    testnet_label: int = -1  # ground-truth label exposed on testnet only

    image: str = pydantic.Field(title="Image", description="A base64 encoded image", default="", frozen=False)

    prediction: float = pydantic.Field(
        title="Prediction",
        description="Probability that the image is AI generated/modified",
        default=-1.0,
        frozen=False,
    )

    def deserialize(self) -> float:
        return self.prediction
