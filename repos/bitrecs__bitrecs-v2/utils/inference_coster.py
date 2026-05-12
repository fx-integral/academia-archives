import httpx
import time
import asyncio
import utils.logger as logger
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from llm.llm_provider import LLM

async def pre_cache_inference_cost():
    for provider in [LLM.CHUTES, LLM.OPEN_ROUTER]:
        try:            
            dummy_coster = InferenceCoster(provider.name, "ignored")
            await dummy_coster._get_cached_data(provider.name)
            logger.info(f"Preloaded cache for provider: {provider.name}")
        except Exception as e:
            logger.error(f"Failed to preload cache for {provider.name}: {e}")


@dataclass  
class CostResult:
    """
    Represents the cost result for a given model, including input and output costs.
    Costs are expected to be in USD per million tokens.
    """
    input: float
    output: float


class InferenceCoster:    
    _cache: Dict[str, Tuple[Optional[Dict[str, Any]], datetime]] = {}
    _lock = asyncio.Lock()
    _cache_ttl = timedelta(minutes=45)

    def __init__(self, provider: str, model_name: str):
        self.provider = provider
        self.model_name = model_name
        if not LLM.is_valid(self.provider):
            raise ValueError(f"Unsupported provider: {self.provider}")

    async def _fetch_chutes_data(self) -> Optional[Dict[str, Any]]:
        """
        Fetch all models data from Chutes API with pagination.
        """
        try:
            page = 0
            limit = 500
            all_items = []
            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            response = await client.get(f"https://api.chutes.ai/chutes/?page={page}&limit={limit}")
                            response.raise_for_status()
                            break
                        except httpx.HTTPStatusError as e:
                            if e.response.status_code == 429 and attempt < max_retries - 1:
                                wait_time = 2 ** attempt
                                logger.warning(f"Rate limited (429), retrying in {wait_time}s...")
                                await asyncio.sleep(wait_time)
                            else:
                                raise
                    
                    data = response.json()
                    items = data.get("items", [])
                    all_items.extend(items)
                    if not items or len(all_items) >= data.get('total', 0):
                        break
                    page += 1
            return {"items": all_items}
        except Exception as e:
            logger.error(f"Error fetching data from Chutes: {e}")
            return None

    async def _fetch_openrouter_data(self) -> Optional[Dict[str, Any]]:
        """
        Fetch all models data from OpenRouter API.
        """
        try:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get("https://openrouter.ai/api/v1/models")
                        response.raise_for_status()
                        return response.json()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(f"Rate limited (429), retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        raise
        except Exception as e:
            logger.error(f"Error fetching data from OpenRouter: {e}")
            return None

    async def _get_cached_data(self, provider: str) -> Optional[Dict[str, Any]]:
        """
        Get cached data for the provider, refreshing if stale.
        """
        # Fast path: check without lock
        if provider in self._cache:
            data, timestamp = self._cache[provider]
            if datetime.now() - timestamp < self._cache_ttl:
                return data
        # Slow path: acquire lock to refresh
        async with self._lock:            
            if provider in self._cache:
                data, timestamp = self._cache[provider]
                if datetime.now() - timestamp < self._cache_ttl:
                    return data

            # Fetch fresh data
            if provider.upper() == LLM.CHUTES.name.upper():
                data = await self._fetch_chutes_data()
            elif provider.upper() == LLM.OPEN_ROUTER.name.upper():
                data = await self._fetch_openrouter_data()
            else:
                data = None
            
            self._cache[provider] = (data, datetime.now())
            return data

    async def fetch_cost(self) -> Optional[CostResult]:
        """
        Fetch pricing for a given model based on the provider, using cached data.
        """
        data = await self._get_cached_data(self.provider)
        if data is None:
            return None
        
        if self.provider.upper() == LLM.CHUTES.name.upper():
            target_id = self.model_name.lower()
            target_base = target_id.split("/")[-1]
            items = data.get("items", [])
            for item in items:
                item_name = item.get("name", "").lower()
                if item_name == target_id or item_name.endswith("/" + target_base):
                    price_info = item.get("current_estimated_price", {}).get("per_million_tokens", {})
                    input_price = price_info.get("input", {}).get("usd", 0.0)
                    output_price = price_info.get("output", {}).get("usd", 0.0)
                    return CostResult(input=input_price, output=output_price)
            logger.warning(f"Model {self.model_name} not found in cached Chutes data.")
            return None
        
        elif self.provider.upper() == LLM.OPEN_ROUTER.name.upper():
            models = data.get("data", [])
            target_id = self.model_name.lower()
            target_base = target_id.split("/")[-1]
            
            # First pass: exact match
            for model in models:
                model_id_lower = model["id"].lower()
                if model_id_lower == target_id or model_id_lower.endswith("/" + target_base):
                    pricing = model.get("pricing", {})
                    input_cost = float(pricing.get("prompt", 0.0)) * 1e6
                    output_cost = float(pricing.get("completion", 0.0)) * 1e6
                    return CostResult(input=input_cost, output=output_cost)
            
            # Second pass: remove '-instruct'
            fallback_target = target_id.replace("-instruct", "")
            fallback_base = fallback_target.split("/")[-1]
            for model in models:
                model_id_lower = model["id"].lower().replace("-instruct", "")
                if model_id_lower == fallback_target or model_id_lower.endswith("/" + fallback_base):
                    pricing = model.get("pricing", {})
                    input_cost = float(pricing.get("prompt", 0.0)) * 1e6
                    output_cost = float(pricing.get("completion", 0.0)) * 1e6
                    return CostResult(input=input_cost, output=output_cost)
            
            logger.warning(f"Model {self.model_name} not found in cached OpenRouter data.")
            return None
        
        else:
            logger.warning(f"Provider {self.provider} not supported for pricing fetch.")
            return None

    async def calculate_cost(self, input_tokens: float, output_tokens: float) -> Optional[float]:
        pricing = await self.fetch_cost()
        if pricing is None:
            logger.warning("Pricing information not available, cannot calculate cost.")
            logger.warning(f"Provider: {self.provider}, Model: {self.model_name}")
            return None
        total_cost = (input_tokens / 1e6) * pricing.input + (output_tokens / 1e6) * pricing.output
        return total_cost
    
    async def cost_estimate(self, input_tokens: float, output_tokens: float) -> Optional[CostResult]:
        pricing = await self.fetch_cost()
        if pricing is None:
            logger.warning("Pricing information not available, cannot provide cost estimate.")
            logger.warning(f"Provider: {self.provider}, Model: {self.model_name}")
            return None
        input_cost = (input_tokens / 1e6) * pricing.input
        output_cost = (output_tokens / 1e6) * pricing.output
        return CostResult(input=input_cost, output=output_cost)
    
    async def models(self) -> Optional[Dict[str, Any]]:
        return await self._get_cached_data(self.provider)