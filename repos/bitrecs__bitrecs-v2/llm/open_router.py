import time
import json
import httpx
import logging
from llm.llm_provider import LLM
from utils.token import get_token_count

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class OpenRouter:    
    def __init__(self, 
                 key,
                 model="google/gemini-flash-1.5-8b", 
                 system_prompt="You are a helpful assistant.", 
                 temp=0.0,
                 embedding_dimensions=768
        ):

        self.OPENROUTER_API_KEY = key
        if not self.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self.model = model       
        self.system_prompt = system_prompt
        self.temp = temp
        self.embedding_dimensions = embedding_dimensions
        self.provider = LLM.OPEN_ROUTER.name

    def get_embeddings(self, text: str | list[str]) -> list[float] | list[list[float]]:
        """
        Get embeddings for a single text or batch of texts.
        
        Args:
            text: A single string or list of strings to embed
            
        Returns:
            - If input is str: returns list[float] (single embedding)
            - If input is list[str]: returns list[list[float]] (multiple embeddings)
        """
        url = "https://openrouter.ai/api/v1/embeddings"
        
        # if "qwen3-embedding-8b" not in self.model:
        #     raise ValueError("Only qwen/qwen3-embedding-8b model is supported for embeddings")
        
        headers = {
            "Authorization": f"Bearer {self.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://bitrecs.ai",
            "X-Title": "bitrecs"
        }
        data = {
            "model": self.model,
            "input": text,
            "dimensions": self.embedding_dimensions  # Request specific dimensions
        }
        timeout = (5, 30)  # connect, read timeout
        max_retries = 2  # 3 total attempts
        for attempt in range(max_retries + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(
                        url,
                        headers=headers,
                        json=data
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    # If single text input, return single embedding
                    if isinstance(text, str):
                        return result['data'][0]['embedding']
                    
                    # If list input, return all embeddings
                    return [item['embedding'] for item in result['data']]
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < max_retries:
                    wait_time = 1 * (attempt + 1)  # Linear backoff: 1s, 2s
                    logger.warning(f"429 received, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(wait_time)
                    continue
                else:
                    raise RuntimeError(f"OpenRouter request failed: {e}") from e
            except httpx.ConnectTimeout:
                if attempt < max_retries:
                    wait_time = 1 * (attempt + 1)
                    logger.warning(f"Connect timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(wait_time)
                    continue
                raise TimeoutError(f"OpenRouter connect timed out after {timeout[0]}s")
            except httpx.ReadTimeout:
                if attempt < max_retries:
                    wait_time = 1 * (attempt + 1)
                    logger.warning(f"Read timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(wait_time)
                    continue
                raise TimeoutError(f"OpenRouter read timed out after {timeout[1]}s")
            except httpx.RequestError as e:
                if attempt < max_retries:
                    wait_time = 1 * (attempt + 1)
                    logger.warning(f"Request error, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(wait_time)
                    continue
                raise RuntimeError(f"OpenRouter request failed: {e}") from e
        

    def call_open_router(self, prompt) -> str:
        if not prompt or len(prompt) < 10:
            raise ValueError()

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://bitrecs.ai",
            "X-Title": "bitrecs"
        }
        reasoning = {
            "enabled": False,
            "exclude": True,
            "effort": "minimal"
        }
        # Handle specific models that require different reasoning settings
        if "gpt-5" in self.model.lower():
            reasoning = {
                "exclude": True,
                "effort": "minimal"
            }

        data = {
            "model": self.model,
            "messages": [                
                {
                    "role": "user", 
                    "content": prompt
                }],
            "reasoning": reasoning,
            "stream": False,
            "temperature": self.temp,
            "max_tokens": 4096
        }
        
        timeout = (5, 60) #connect, read timeout
        try:
            with httpx.Client(timeout=timeout) as client:
                if logger.level >= logging.DEBUG:
                    start_time = time.perf_counter()
                    content = data["messages"][0]["content"]
                    token_count = get_token_count(content)
                    logger.debug(f"OPEN_ROUTER request token count: {token_count} tokens")
                response = client.post(
                    url,
                    headers=headers,
                    json=data
                )
                response.raise_for_status()
                data = response.json()
                if logger.level >= logging.DEBUG:
                    end_time = time.perf_counter()
                    duration = end_time - start_time
                    logger.debug(f"OPEN_ROUTER request completed in {duration:.2f}s")
                #print(data)
                return data['choices'][0]['message']['content']
        except httpx.ConnectTimeout:
            raise TimeoutError(f"OpenRouter connect timed out after {timeout[0]}s")
        except httpx.ReadTimeout:
            raise TimeoutError(f"OpenRouter read timed out after {timeout[1]}s")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"OpenRouter request failed: {e}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"OpenRouter request failed: {e}") from e