# The MIT License (MIT)
# Copyright © 2025 Level114 Team

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

import time
from functools import lru_cache, wraps
from typing import Callable, Any


def ttl_cache(maxsize: int = 128, typed: bool = False, ttl: int = -1):
    """
    LRU Cache with TTL (time to live) support.
    
    Args:
        maxsize (int): Maximum number of entries to store in the cache.
        typed (bool): Whether to cache based on argument types.
        ttl (int): Time to live in seconds. If -1, no TTL is applied.
        
    Returns:
        Decorator function.
    """
    if ttl <= 0:
        ttl = 65536
        
    hash_gen = _ttl_hash_gen(ttl)
    
    def wrapper(func: Callable) -> Callable:
        @lru_cache(maxsize, typed)
        def ttl_func(ttl_hash, *args, **kwargs):
            return func(*args, **kwargs)
        
        def wrapped(*args, **kwargs) -> Any:
            th = next(hash_gen)
            return ttl_func(th, *args, **kwargs)
        
        wrapped.cache_info = ttl_func.cache_info
        wrapped.cache_clear = ttl_func.cache_clear
        
        return wrapped
    
    return wrapper


def _ttl_hash_gen(seconds: int):
    """
    Generate a hash that changes every `seconds` seconds.
    
    Args:
        seconds (int): Number of seconds before hash changes.
        
    Yields:
        int: Current time-based hash.
    """
    start_time = time.time()
    while True:
        yield round((time.time() - start_time) / seconds)


@ttl_cache(maxsize=1, ttl=12)
def ttl_get_block(self) -> int:
    """
    Get the current block number with TTL caching.
    
    Args:
        self: The neuron instance (for accessing subtensor).
        
    Returns:
        int: Current block number.
    """
    return self.subtensor.get_current_block()
