import gc
import random
import bittensor as bt
import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoTokenizer, Blip2ForConditionalGeneration, Blip2Processor
from transformers import logging as transformers_logging
from transformers import pipeline

from natix.validator.config import HUGGINGFACE_CACHE_DIR


class PromptGenerator:
    """
    A class for generating and moderating image annotations using transformer models.

    This class provides functionality to generate descriptive captions for images
    using BLIP2 models and optionally moderate the generated text using a separate
    language model.
    """

    def __init__(
        self,
        vlm_name: str,
        llm_name: str,
        device: str = 'cuda',
    ) -> None:
        """
        Initialize the ImageAnnotationGenerator with specific models and device settings.

        Args:
            model_name: The name of the BLIP model for generating image captions.
            text_moderation_model_name: The name of the model used for moderating
                text descriptions.
            device: The device to use.
            apply_moderation: Flag to determine whether text moderation should be
                applied to captions.
        """
        self.vlm_name = vlm_name
        self.llm_name = llm_name
        self.vlm_processor = None
        self.vlm = None
        self.llm_pipeline = None
        self.device = device

    def are_models_loaded(self) -> bool:
        return (self.vlm is not None) and (self.llm_pipeline is not None)

    def load_models(self) -> None:
        """
        Load the necessary models for image annotation and text moderation onto
        the specified device.
        """
        if self.are_models_loaded():
            bt.logging.warning("Models already loaded")
            return

        bt.logging.info(f"Loading caption generation model {self.vlm_name}")
        self.vlm_processor = Blip2Processor.from_pretrained(self.vlm_name, cache_dir=HUGGINGFACE_CACHE_DIR)
        self.vlm = Blip2ForConditionalGeneration.from_pretrained(
            self.vlm_name, 
            torch_dtype=torch.float32,
            cache_dir=HUGGINGFACE_CACHE_DIR
        )
        self.vlm.to(self.device)
        
        # Convert all float32 parameters to float16 to save memory
        for param in self.vlm.parameters():
            if param.dtype == torch.float32:
                param.data = param.data.to(torch.float16)
        
        # Enable CPU offloading for memory efficiency
        if hasattr(self.vlm, 'enable_model_cpu_offload'):
            self.vlm.enable_model_cpu_offload()
        bt.logging.info(f"Loaded image annotation model {self.vlm_name}")

        bt.logging.info(f"Loading caption moderation model {self.llm_name}")
        llm = AutoModelForCausalLM.from_pretrained(self.llm_name, torch_dtype=torch.bfloat16, cache_dir=HUGGINGFACE_CACHE_DIR)
        tokenizer = AutoTokenizer.from_pretrained(self.llm_name, cache_dir=HUGGINGFACE_CACHE_DIR)
        llm = llm.to(self.device)
        
        # Convert any float32 parameters to float16 for memory efficiency
        for param in llm.parameters():
            if param.dtype == torch.float32:
                param.data = param.data.to(torch.float16)

        bt.logging.info(f"DEVICE WHERE ERROR OCCURS: {self.device}")
        self.llm_pipeline = pipeline(
            "text-generation",
            model=llm,
            tokenizer=tokenizer,
        )
        bt.logging.info(f"Loaded caption moderation model {self.llm_name}")

    def clear_gpu(self) -> None:
        """
        Clear GPU memory by moving models back to CPU and deleting them,
        followed by collecting garbage.
        """
        bt.logging.info("Clearing GPU memory after prompt generation")
        if self.vlm:
            self.vlm.to("cpu")
            del self.vlm
            self.vlm = None

        if self.vlm_processor:
            del self.vlm_processor
            self.vlm_processor = None

        if self.llm_pipeline:
            self.llm_pipeline.model.to("cpu")
            del self.llm_pipeline
            self.llm_pipeline = None

        # Multiple rounds of garbage collection and cache clearing
        for _ in range(3):
            gc.collect()
            torch.cuda.empty_cache()
        
        bt.logging.info("GPU memory cleared")

    def generate(
        self,
        image: Image.Image,
        label: int = None,
        max_new_tokens: int = 60,
        verbose: bool = False,
    ) -> str:
        if not verbose:
            transformers_logging.set_verbosity_error()

        inputs = self.vlm_processor(
            images=image,
            return_tensors="pt"
        ).to(self.device)
        generated_ids = self.vlm.generate(**inputs, max_new_tokens=max_new_tokens)
        caption = self.vlm_processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

        if not verbose:
            transformers_logging.set_verbosity_info()

        if not caption:
            caption = "Dashcam view of road scene."
    
        moderated_description = self.moderate(caption, label, max_new_tokens=60)
        moderated_description = self._enforce_clip_token_limit(moderated_description, max_tokens=77)
        return moderated_description

    def moderate(
        self,
        description: str,
        label: int = None,
        max_new_tokens: int = 60,
    ) -> str:
        if label == 1:
            system_content = (
                "[INST]Write ONE sentence under 40 words. "
                "Start exactly with 'Photorealistic dashcam footage of active roadwork'. "

                "The scene MUST clearly depict roadwork activity. "
                "Include EXACTLY 1 primary element from: worker in safety vest, traffic cone, barrier, construction machine. "

                "The element must appear at realistic scale and distance, integrated naturally into the road scene. "
                "It must NOT be a close-up or dominate the frame. Avoid foreground exaggeration. "

                "The camera perspective is from a moving vehicle, showing a wide road view. "

                "Do NOT include unrelated scenes (traffic lights, random vehicles, cyclists, empty roads). "
                "Do NOT change the count (e.g., if one cone is specified, show exactly one). "

                "Ensure the scene cannot be mistaken for normal traffic.[/INST]"
            )

        elif label == 0:
            system_content = (
                "[INST]Write a SINGLE sentence under 40 words. "
                "Start with 'Photorealistic dashcam footage of'. "
                "Describe a normal road scene with clear traffic and no construction. "
                "Focus on road type, traffic, weather. No paragraphs, no filler text.[/INST]"
            )

        else:
            system_content = (
                "[INST]Write a SINGLE sentence under 40 words. "
                "Start with 'Photorealistic dashcam footage of'. "
                "Describe the road scene. No paragraphs, no filler text.[/INST]"
            )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": description},
        ]

        try:
            moderated_text = self.llm_pipeline(
                messages,
                max_new_tokens=max_new_tokens,
                pad_token_id=self.llm_pipeline.tokenizer.eos_token_id,
                return_full_text=False,
            )[0]["generated_text"]

            moderated_text = moderated_text.strip()

            if label == 1:
                required_tokens = [
                    "a single orange traffic cone",
                    "one worker in a safety vest",
                    "a parked construction vehicle",
                    "a temporary roadwork sign",
                    "a small barrier"
                ]

                # Force a very low count
                chosen = random.sample(required_tokens, 1) # Only pick ONE specific element
                
                if "active roadwork" in moderated_text:
                    # Replace the generic term with a specific, singular instance
                    moderated_text = moderated_text.replace(
                        "active roadwork",
                        f"a localized roadwork zone featuring {chosen[0]}",
                        1
                    )

            moderated_text = moderated_text.split(".")[0] + "."

            return moderated_text

        except Exception as e:
            bt.logging.error(f"Moderation error: {e}", exc_info=True)
            return description

    def _enforce_clip_token_limit(self, prompt: str, max_tokens: int = 77) -> str:
        try:
            tokenizer = self.llm_pipeline.tokenizer
            tokens = tokenizer(prompt, truncation=False)["input_ids"]

            if len(tokens) <= max_tokens:
                return prompt

            truncated_tokens = tokens[:max_tokens]
            truncated_prompt = tokenizer.decode(truncated_tokens, skip_special_tokens=True)

            # Ensure clean ending
            truncated_prompt = truncated_prompt.rsplit(",", 1)[0].rstrip()
            if not truncated_prompt.endswith("."):
                truncated_prompt += "."

            return truncated_prompt

        except Exception as e:
            bt.logging.warning(f"Token limit enforcement failed: {e}")
            return prompt
