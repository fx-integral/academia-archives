"""
LLM Generator

Unified story generation backend supporting both local and cloud LLMs.

Local Mode:
  - Ollama (localhost:11434)
  - vLLM (OpenAI-compatible endpoint)

Cloud Mode:
  - OpenAI (GPT-4, GPT-4o-mini)
  - Google Gemini
  - Zhipu AI (GLM-4)
"""

import os
import time
import asyncio
import logging
from typing import Dict, Optional
from .base import StoryGenerator, GenerationError, GeneratorConfigError

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class LLMGenerator(StoryGenerator):
    """
    Unified LLM generator for story generation.

    Supports two modes:
    - local: Ollama, vLLM, or any OpenAI-compatible local server
    - cloud: OpenAI, Gemini, Zhipu cloud APIs
    """

    def __init__(self, config: Dict):
        """
        Initialize LLM generator.

        Args:
            config: Configuration dict with mode-specific settings
        """
        super().__init__(config)

        self.mode = config.get("mode", "cloud")
        self.available = False
        self.initialized = False

        if self.mode == "local":
            self._init_local(config.get("local", {}))
        else:
            self._init_cloud(config.get("cloud", {}))

    def _init_local(self, config: Dict):
        """Initialize local LLM backend."""
        self.local_type = config.get("type", "ollama")
        self.local_url = config.get("url", "http://localhost:11434")
        self.model = config.get("model", "qwen2.5:7b")

        if self.local_type == "ollama":
            # Ollama uses its own API format
            self.api_endpoint = f"{self.local_url}/api/generate"
            self.use_chat_format = False
        else:
            # vLLM and others use OpenAI-compatible format
            self.api_endpoint = f"{self.local_url}/v1/chat/completions"
            self.use_chat_format = True

            if OPENAI_AVAILABLE:
                self.client = AsyncOpenAI(
                    api_key="not-needed",
                    base_url=f"{self.local_url}/v1"
                )

        self.available = True
        self.initialized = True
        logger.info(f"Local LLM initialized: {self.local_type} @ {self.local_url}")

    def _init_cloud(self, config: Dict):
        """Initialize cloud LLM backend."""
        self.provider = config.get("provider", "openai")
        api_key_env = config.get("api_key_env", "OPENAI_API_KEY")
        self.model = config.get("model", "gpt-4o-mini")
        self.endpoint = config.get("endpoint")

        self.api_key = os.getenv(api_key_env)

        if not self.api_key:
            logger.warning(f"{api_key_env} not found in environment")
            return

        self.available = True

        if self.provider == "openai":
            if not OPENAI_AVAILABLE:
                raise GeneratorConfigError("openai library not installed")
            if self.endpoint:
                self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.endpoint)
            else:
                self.client = AsyncOpenAI(api_key=self.api_key)

        elif self.provider == "gemini":
            if not GEMINI_AVAILABLE:
                raise GeneratorConfigError("google-generativeai not installed")
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)

        elif self.provider == "zhipu":
            if not HTTPX_AVAILABLE:
                raise GeneratorConfigError("httpx not installed")
            self.zhipu_endpoint = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

        self.initialized = True
        logger.info(f"Cloud LLM initialized: {self.provider}/{self.model}")

    async def generate(self, input_data: Dict) -> Dict:
        """Generate story content."""
        if not self.available:
            raise GenerationError("LLM Generator not available")

        start_time = time.time()

        try:
            if self.mode == "local":
                result = await self._generate_local(input_data)
            else:
                result = await self._generate_cloud(input_data)

            generation_time = time.time() - start_time

            return {
                "generated_content": result,
                "model": self.model,
                "mode": self.mode,
                "generation_time": generation_time,
                "metadata": {
                    "type": self.local_type if self.mode == "local" else self.provider
                }
            }

        except Exception as e:
            raise GenerationError(f"Generation failed: {str(e)}")

    async def _generate_local(self, input_data: Dict) -> str:
        """Generate using local LLM."""
        if self.local_type == "ollama":
            return await self._generate_ollama(input_data)
        else:
            # vLLM or other OpenAI-compatible
            return await self._generate_openai_compatible(input_data)

    async def _generate_ollama(self, input_data: Dict) -> str:
        """Generate using Ollama API."""
        if not HTTPX_AVAILABLE:
            raise GenerationError("httpx not installed")

        prompt = self._build_prompt(input_data)

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                self.api_endpoint,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 2048
                    }
                }
            )
            response.raise_for_status()
            return response.json().get("response", "")

    async def _generate_openai_compatible(self, input_data: Dict) -> str:
        """Generate using OpenAI-compatible API (vLLM, etc.)."""
        messages = self._build_messages(input_data)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.8,
            max_tokens=2048
        )

        return response.choices[0].message.content

    async def _generate_cloud(self, input_data: Dict) -> str:
        """Generate using cloud API."""
        if self.provider == "openai":
            return await self._generate_openai(input_data)
        elif self.provider == "gemini":
            return await self._generate_gemini(input_data)
        elif self.provider == "zhipu":
            return await self._generate_zhipu(input_data)
        else:
            raise GenerationError(f"Unsupported provider: {self.provider}")

    async def _generate_openai(self, input_data: Dict) -> str:
        """Generate using OpenAI API."""
        messages = self._build_messages(input_data)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.8,
            max_tokens=2048
        )

        return response.choices[0].message.content

    async def _generate_gemini(self, input_data: Dict) -> str:
        """Generate using Gemini API."""
        prompt = self._build_prompt(input_data)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            self.client.generate_content,
            prompt
        )

        return response.text

    async def _generate_zhipu(self, input_data: Dict) -> str:
        """Generate using Zhipu API."""
        messages = self._build_messages(input_data)

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.zhipu_endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.8,
                    "max_tokens": 2048
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _build_messages(self, input_data: Dict) -> list:
        """Build chat messages for the LLM."""
        user_input = input_data.get("user_input", "")
        blueprint = input_data.get("blueprint", {})

        content = f"Generate engaging story content based on:\n\n"
        content += f"User Request: {user_input}\n\n"

        if blueprint:
            content += f"Blueprint: {blueprint}\n\n"

        return [
            {
                "role": "system",
                "content": "You are a creative story writer for an interactive story game."
            },
            {
                "role": "user",
                "content": content
            }
        ]

    def _build_prompt(self, input_data: Dict) -> str:
        """Build prompt string for non-chat APIs."""
        user_input = input_data.get("user_input", "")
        blueprint = input_data.get("blueprint", {})

        prompt = "You are a creative story writer.\n\n"
        prompt += f"User Request: {user_input}\n\n"

        if blueprint:
            prompt += f"Blueprint: {blueprint}\n\n"

        prompt += "Generate engaging story content:"

        return prompt

    def get_mode(self) -> str:
        """Return current mode."""
        return self.mode

    def get_model_info(self) -> Dict:
        """Get model information."""
        if self.mode == "local":
            return {
                "name": self.model,
                "version": None,
                "provider": self.local_type,
                "parameters": {"url": self.local_url}
            }
        else:
            return {
                "name": self.model,
                "version": None,
                "provider": self.provider,
                "parameters": {}
            }

    async def health_check(self) -> bool:
        """Check if LLM is available."""
        return self.available
