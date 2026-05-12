"""
Cryptocurrency network statistics fetcher with caching.

Provides methods to fetch current network statistics for various cryptocurrencies
such as difficulty, with built-in caching to minimize API calls.
"""

import logging
import requests
import cachetools
from cachetools import TTLCache

logger = logging.getLogger(__name__)

DIFFICULTY_TTL = 12 * 60 * 60  # 12 hours
_difficulty_cache = TTLCache(maxsize=10, ttl=DIFFICULTY_TTL)

# Fallback difficulties for different coins (LTC+DOGE merged mining)
FALLBACK_DIFFICULTIES = {
    "litecoin": 95_827_342,  # ~95.8M fallback for LTC (updated from API)
    "dogecoin": 47_143_814,   # ~47.1M fallback for DOGE (updated from API)
}

API_TIMEOUT = 10  # seconds

# API endpoints for different coins (LTC+DOGE merged mining)
DIFFICULTY_APIS = {
    "litecoin": "https://api.blockchair.com/litecoin/stats",
    "dogecoin": "https://api.blockchair.com/dogecoin/stats",
}


def _fetch_difficulty(coin: str = "litecoin") -> float:
    """
    Fetch current network difficulty for specified coin.

    Args:
        coin: The cryptocurrency name (litecoin, dogecoin)

    Returns:
        float: Current network difficulty

    Raises:
        Exception: If API request fails or returns invalid data
    """
    api_url = DIFFICULTY_APIS.get(coin.lower())
    if not api_url:
        raise Exception(f"Unsupported coin: {coin}")
    
    response = requests.get(api_url, timeout=API_TIMEOUT)
    if response.status_code == 200:
        # Blockchair API returns JSON with stats for LTC and DOGE
        data = response.json()
        difficulty = float(data["data"]["difficulty"])
        
        logger.info(f"Fetched {coin} difficulty: {difficulty:,.0f}")
        return difficulty
    else:
        raise Exception(f"API returned status {response.status_code}")


@cachetools.cached(cache=_difficulty_cache)
def get_current_difficulty(coin: str = "litecoin") -> float:
    """
    Get current network difficulty for specified coin with caching.

    Args:
        coin: The cryptocurrency name (litecoin, dogecoin)

    Returns:
        float: Current network difficulty, or fallback value if fetch fails
    """
    try:
        return _fetch_difficulty(coin)
    except requests.Timeout:
        logger.warning(f"Timeout fetching {coin} difficulty after {API_TIMEOUT}s")
    except Exception as e:
        logger.error(f"Error fetching {coin} difficulty: {e}")

    fallback = FALLBACK_DIFFICULTIES.get(coin.lower(), FALLBACK_DIFFICULTIES["litecoin"])
    logger.warning(f"Using fallback {coin} difficulty: {fallback:,.0f}")
    return fallback
