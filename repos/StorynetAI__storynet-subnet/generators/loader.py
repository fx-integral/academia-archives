"""
Generator Loader

Loads and manages story generation backends.
"""

import yaml
import os
from typing import Dict, Optional
from .base import StoryGenerator
from .llm_generator import LLMGenerator


class GeneratorLoader:
    """
    Generator loader for story generation.

    Loads generator based on configuration file.
    Supports both local (Ollama, vLLM) and cloud (OpenAI, Gemini, Zhipu) backends.

    Example:
        loader = GeneratorLoader()
        result = await loader.generate({"user_input": "..."})
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize loader.

        Args:
            config_path: Path to YAML config file (default: config/generator_config.yaml)
        """
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config",
                "generator_config.yaml"
            )

        self.config_path = config_path
        self.config = self._load_config()
        self.generator: Optional[StoryGenerator] = None

        self._load_generator()

    def _load_config(self) -> Dict:
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_path):
            return self._default_config()

        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def _default_config(self) -> Dict:
        """Return default configuration."""
        return {
            "generator": {
                "mode": "local",
                "local": {
                    "type": "ollama",
                    "url": "http://localhost:11434",
                    "model": "qwen2.5:7b"
                },
                "cloud": {
                    "provider": "openai",
                    "api_key_env": "OPENAI_API_KEY",
                    "model": "gpt-4o-mini"
                }
            }
        }

    def _load_generator(self):
        """Load generator based on config."""
        gen_config = self.config.get("generator", {})

        try:
            gen = LLMGenerator(gen_config)
            if gen.available:
                self.generator = gen
                return
        except Exception as e:
            raise RuntimeError(f"Failed to load generator: {e}")

        raise RuntimeError(
            "No generator available. Check your configuration."
        )

    async def generate(self, input_data: Dict) -> Dict:
        """
        Generate story content.

        Args:
            input_data: Input data for generation

        Returns:
            Generated result dict
        """
        if not self.generator:
            raise RuntimeError("No generator loaded")

        return await self.generator.generate(input_data)

    def get_mode(self) -> str:
        """Get current generator mode."""
        if not self.generator:
            return "none"
        return self.generator.get_mode()

    def get_model_info(self) -> Dict:
        """Get current model info."""
        if not self.generator:
            return {}
        return self.generator.get_model_info()

    async def health_check(self) -> bool:
        """Check if generator is healthy."""
        if not self.generator:
            return False
        return await self.generator.health_check()

    def is_fallback(self) -> bool:
        """Check if using fallback generator."""
        return False
