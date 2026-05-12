"""
Mining pool difficulty retrieval module
Retrieve real mining pool difficulty from mining-pool API
"""

import os
import logging
import requests
from typing import Optional


class PoolDifficultyAPI:
    """Mining pool difficulty API client"""
    
    def __init__(self, api_url: Optional[str] = None):
        """
        InitializeMining pool difficulty API client
        
        Args:
            api_url: Mining pool API URL
        """
        self.api_url = api_url or os.getenv("MINING_POOL_API_URL", "http://localhost:8001")
        self.timeout = 10
        
    def get_pool_difficulty(self) -> Optional[float]:
        """
        Get mining pool difficulty
        
        Returns:
            float: Mining pool difficulty value
        """
        try:
            url = f"{self.api_url}/api/pool/difficulty"
            
            logging.info(f"Fetching pool difficulty from: {url}")
            
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            pool_difficulty = data.get("pool_difficulty")
            
            if pool_difficulty is not None:
                logging.info(f"Successfully fetched pool difficulty: {pool_difficulty}")
                return float(pool_difficulty)
            else:
                logging.error(f"Pool difficulty not found in response: {data}")
                return None
                
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch pool difficulty from {url}: {e}")
            return None
        except (ValueError, KeyError) as e:
            logging.error(f"Failed to parse pool difficulty response: {e}")
            return None
    
    def get_pool_difficulty_with_fallback(self, fallback_difficulty: float = 0.0001) -> float:
        """
        Get mining pool difficulty，Use default value on failure
        
        Args:
            fallback_difficulty: Default difficulty value
            
        Returns:
            float: Mining pool difficulty value
        """
        difficulty = self.get_pool_difficulty()
        
        if difficulty is not None:
            return difficulty
        else:
            logging.warning(f"Using fallback pool difficulty: {fallback_difficulty}")
            return fallback_difficulty


# Global instance
_pool_difficulty_api = None


def get_pool_difficulty_api() -> PoolDifficultyAPI:
    """Get global pool difficulty API instance"""
    global _pool_difficulty_api
    if _pool_difficulty_api is None:
        _pool_difficulty_api = PoolDifficultyAPI()
    return _pool_difficulty_api


def get_pool_difficulty() -> Optional[float]:
    """Get current pool difficulty"""
    api = get_pool_difficulty_api()
    return api.get_pool_difficulty()


def get_pool_difficulty_with_fallback(fallback_difficulty: float = 0.0001) -> float:
    """Get pool difficulty with fallback value if API fails"""
    api = get_pool_difficulty_api()
    return api.get_pool_difficulty_with_fallback(fallback_difficulty)
