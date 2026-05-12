from typing import Any, Dict, List, Optional

import numpy as np
import torch
from diffusers import (
    StableDiffusionXLImg2ImgPipeline,
    StableDiffusionXLPipeline,
)

from natix.validator.config import HUGGINGFACE_CACHE_DIR  # noqa: re-exported for convenience

IMAGE_ANNOTATION_MODEL: str = "Salesforce/blip2-opt-2.7b-coco"
TEXT_MODERATION_MODEL: str = (
    "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"
    if torch.cuda.is_available()
    else "unsloth/Llama-3.2-1B-Instruct"
)

T2I_MODELS: Dict[str, Dict[str, Any]] = {
    "stabilityai/stable-diffusion-xl-base-1.0": {
        "pipeline_cls": StableDiffusionXLPipeline,
        "from_pretrained_args": {
            "use_safetensors": True,
            "torch_dtype": torch.float32 if not torch.cuda.is_available() else torch.float16,
        },
        "use_autocast": False,
        "enable_model_cpu_offload": True,
        "vae_enable_slicing": True,
        "vae_enable_tiling": True,
        "generate_args": {
            "guidance_scale": 8.5,
            "num_inference_steps": 25,
            "generator": torch.Generator("cuda" if torch.cuda.is_available() else "cpu"),
            "negative_prompt": (
                "cluttered, overcrowded, hundreds of cones, wall of traffic cones, "
                "excessive machinery, messy construction site, crowded road, "
                "over-populated, surreal amount of equipment, "
                "cartoon, anime, painting, drawing, artistic, stylized, illustration,"
                "sketch, unrealistic, fake, artificial, 3d render, cgi, video game,"
                "fantasy, sci-fi, aerial view, bird's eye view, satellite view, drone footage,"
                "helicopter view, top-down view, security camera, cctv, surveillance camera,"
                "indoor scene, interior, portrait, face, person close-up, selfie, vibrant colors,"
                "oversaturated, neon, glowing, night vision, thermal imaging, fisheye lens, wide angle distortion,"
                "motion blur, blurry, out of focus, unfocused, soft focus, speed blur, camera shake, movement blur"
            ),
        },
    },
}
T2I_MODEL_NAMES: List[str] = list(T2I_MODELS.keys())

I2I_MODELS: Dict[str, Dict[str, Any]] = {
    "stabilityai/stable-diffusion-xl-base-1.0-img2img": {
        "pipeline_cls": StableDiffusionXLImg2ImgPipeline,
        "from_pretrained_args": {
            "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
            "use_safetensors": True,
            "torch_dtype": torch.float16,
            "variant": "fp16",
        },
        "use_autocast": False,
        "enable_model_cpu_offload": True,
        "vae_enable_slicing": True,
        "vae_enable_tiling": True,
        "generate_args": {
            "guidance_scale": 8.5,
            "num_inference_steps": 25,
            "strength": 0.7,
            "generator": torch.Generator("cuda" if torch.cuda.is_available() else "cpu"),
            "negative_prompt": (
                "cartoon, anime, painting, drawing, artistic, stylized, illustration, sketch, "
                "unrealistic, fake, artificial, 3d render, cgi, video game, fantasy, sci-fi, "
                "aerial view, bird's eye view, satellite view, drone footage, helicopter view, "
                "top-down view, security camera, cctv, surveillance camera, indoor scene, interior, "
                "portrait, face, person close-up, selfie, vibrant colors, oversaturated, neon, glowing, "
                "night vision, thermal imaging, fisheye lens, wide angle distortion"
            ),
        },
    }
}
I2I_MODEL_NAMES: List[str] = list(I2I_MODELS.keys())

MODELS: Dict[str, Dict[str, Any]] = {**T2I_MODELS, **I2I_MODELS}
MODEL_NAMES: List[str] = list(MODELS.keys())


def get_modality(model_name: str) -> str:
    if model_name in T2I_MODEL_NAMES + I2I_MODEL_NAMES:
        return "image"


def get_task(model_name: str) -> str:
    if model_name in T2I_MODEL_NAMES:
        return "t2i"
    elif model_name in I2I_MODEL_NAMES:
        return "i2i"


def select_random_model(task: Optional[str] = None) -> str:
    if task is None or task == "random":
        task = np.random.choice(["t2i", "i2i"])
    if task == "t2i":
        return np.random.choice(T2I_MODEL_NAMES)
    elif task == "i2i":
        return np.random.choice(I2I_MODEL_NAMES)
    raise NotImplementedError(f"Unsupported task: {task}")
