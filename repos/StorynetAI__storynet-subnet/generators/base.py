"""
Story Generator Base Class

Defines the abstract interface for story generators.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional


class StoryGenerator(ABC):
    """
    Abstract base class for story generators.

    Miners implement this interface to provide story generation.
    Validators judge output quality.
    """

    def __init__(self, config: Dict):
        """
        Initialize generator with configuration.

        Args:
            config: Dictionary containing generator-specific configuration
        """
        self.config = config
        self.initialized = False
        self.init_time = None

    @abstractmethod
    async def generate(self, input_data: Dict) -> Dict:
        """
        Generate story content from input data.

        Args:
            input_data: Dictionary containing:
                - user_input: str - User's story request
                - blueprint: Optional[Dict] - Story blueprint
                - characters: Optional[Dict] - Character definitions
                - story_arc: Optional[Dict] - Story arc structure
                - chapter_ids: Optional[List[int]] - Chapter IDs

        Returns:
            Dict containing:
                - generated_content: str - The generated story content
                - model: str - Model identifier
                - mode: str - Generation mode
                - generation_time: float - Time taken to generate
                - metadata: Optional[Dict] - Additional metadata

        Raises:
            GenerationError: If generation fails
        """
        pass

    @abstractmethod
    def get_mode(self) -> str:
        """
        Get the generation mode.

        Returns:
            str: Generation mode identifier
        """
        pass

    @abstractmethod
    def get_model_info(self) -> Dict:
        """
        Get information about the model being used.

        Returns:
            Dict containing:
                - name: str - Model name
                - version: Optional[str] - Model version
                - provider: Optional[str] - Provider
                - parameters: Optional[Dict] - Model parameters
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the generator is healthy and ready.

        Returns:
            bool: True if healthy, False otherwise
        """
        pass

    def is_initialized(self) -> bool:
        """Check if generator is initialized."""
        return self.initialized

    def get_init_time(self) -> Optional[float]:
        """Get initialization time."""
        return self.init_time

    async def warmup(self) -> bool:
        """
        Warm up the generator (optional).

        Returns:
            bool: True if warmup successful
        """
        return True

    def _build_prompt(self, input_data: Dict) -> str:
        """
        Build generation prompt from input data.

        Args:
            input_data: Input data containing user_input, task_type, etc.

        Returns:
            Formatted prompt string
        """
        user_input = input_data.get("user_input", "")
        blueprint = input_data.get("blueprint", {})
        characters = input_data.get("characters", {})
        story_arc = input_data.get("story_arc", {})

        prompt_parts = [
            "You are a creative story writer for an interactive story game.",
            "Generate engaging, immersive story content based on the following:",
            ""
        ]

        if user_input:
            prompt_parts.append(f"User Request: {user_input}")
            prompt_parts.append("")

        if blueprint:
            prompt_parts.append(f"Story Blueprint: {blueprint}")
            prompt_parts.append("")

        if characters:
            prompt_parts.append(f"Characters: {characters}")
            prompt_parts.append("")

        if story_arc:
            prompt_parts.append(f"Story Arc: {story_arc}")
            prompt_parts.append("")

        prompt_parts.append("Generated Story:")

        return "\n".join(prompt_parts)


class GenerationError(Exception):
    """Raised when story generation fails."""
    pass


class GeneratorNotInitializedError(Exception):
    """Raised when trying to use uninitialized generator."""
    pass


class GeneratorConfigError(Exception):
    """Raised when generator configuration is invalid."""
    pass
