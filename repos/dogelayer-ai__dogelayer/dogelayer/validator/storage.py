from typing import Optional, Union
import asyncio
import aiohttp
import json
import os
import concurrent.futures
from datetime import datetime

from bittensor.core.config import Config
from bittensor.utils.btlogging import logging

from dogelayer.core.storage import BaseJsonStorage, BaseRedisStorage


class JsonValidatorStorage(BaseJsonStorage):
    def __init__(self, config: Optional["Config"] = None):
        super().__init__(config)
        self.validator_id = self.generate_user_id(config)
        # Unified database API configuration - use environment variables directly
        self.proxy_api_url = os.getenv('SUBNET_PROXY_API_URL', 'http://127.0.0.1:8889')
        self.proxy_api_token = os.getenv('SUBNET_PROXY_API_TOKEN', '')
        
        # Process submit_validator_info configuration, default true
        self.submit_to_db = os.getenv('SUBMIT_VALIDATOR_INFO', 'true').lower() == 'true'
        
        # Create thread pool executor for async tasks
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="db_submit")

    def save_state(self, state: dict) -> None:
        """Save the validator state to a single JSON file."""
        prefix = f"{self.validator_id}_state"
        self.save_data(key="current", data=state, prefix=prefix)
        logging.debug(f"Saved validator state at block {state['current_block']}")
        
        # Additional submission to unified database - moved to main loop scheduled submission, commented out here
        # if self.submit_to_db:
        #     logging.info(f"🔄 Preparing to submit validator info to database: {self.proxy_api_url}")
        #     def run_async_tasks():
        #         try:
        #             loop = asyncio.new_event_loop()
        #             asyncio.set_event_loop(loop)
        #             
        #             # Submit validator info and miner scores in parallel
        #             miner_scores = self._extract_miner_scores(state)
        #             logging.info(f"🔄 Preparing to submit miner score data: {len(miner_scores)} records")
        #             
        #             # Execute in parallel using asyncio.gather
        #             loop.run_until_complete(asyncio.gather(
        #                 self._submit_validator_info(state),
        #                 self._submit_miner_scores(miner_scores),
        #                 return_exceptions=True
        #             ))
        #             
        #         except Exception as e:
        #             logging.error(f"Async submission task failed: {e}")
        #         finally:
        #             loop.close()
        #     
        #     # Submit task using thread pool
        #     self.executor.submit(run_async_tasks)
        # else:
        #     logging.warning("⚠️ submit_to_db configured as False, skipping database submission")

    def load_latest_state(self) -> dict:
        """Load the latest saved validator state."""
        prefix = f"{self.validator_id}_state"
        return self.load_data(key="current", prefix=prefix)
    
    def close(self):
        """Close thread pool executor and release resources"""
        if hasattr(self, 'executor') and self.executor:
            self.executor.shutdown(wait=True)
            logging.debug("Thread pool executor has been closed")
    
    def __del__(self):
        """Destructor to ensure resource cleanup"""
        try:
            if hasattr(self, 'executor') and self.executor:
                self.executor.shutdown(wait=False)  # Don't wait to avoid blocking garbage collection
        except Exception:
            # Ignore exceptions in destructor to avoid affecting garbage collection
            pass
    
    async def _submit_validator_info(self, state: dict) -> None:
        """Submit validator information to unified database"""
        try:
            # Extract validator info from state
            validator_info = self._extract_validator_info(state)
            
            # Send to proxy API
            headers = {}
            if self.proxy_api_token:
                headers['Authorization'] = f'Bearer {self.proxy_api_token}'
                
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.proxy_api_url}/api/validators/submit_info",
                    json=validator_info,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logging.info(f"✅ ValidatorInformationSubmitSuccess: {validator_info['hotkey'][:8]}...")
                    else:
                        logging.warning(f"ValidatorInformationSubmitFailure: {response.status}")
                        
        except Exception as e:
            logging.error(f"SubmitValidatorInformationFailure: {e}")
    
    def _extract_validator_info(self, state: dict) -> dict:
        """Extract required information from validator state"""
        return {
            "hotkey": state.get("hotkey", ""),
            "coldkey": state.get("coldkey", ""),
            "uid": state.get("uid", 0),
            "netuid": state.get("netuid", 2),
            "current_block": state.get("current_block", 0),
            "validator_stake": state.get("validator_stake", 0.0),
            "last_update": state.get("last_update", 0),
            "scores": state.get("scores", []),
            "weights": state.get("weights", []),
            "timestamp": datetime.now().isoformat(),
            "validator_version": state.get("version", "unknown"),
            
            # System monitoring information
            "cpu_usage": state.get("cpu_usage", 0.0),
            "memory_usage": state.get("memory_usage", 0.0),
            "disk_usage": state.get("disk_usage", 0.0),
            "network_latency": state.get("network_latency", 0.0)
        }
    
    def _extract_miner_scores(self, state: dict) -> list:
        """Extract miner score information from validator state"""
        miner_scores = []
        
        # Get basic information
        validator_hotkey = state.get("hotkey", "")
        current_block = state.get("current_block", 0)
        scores = state.get("scores", [])
        hotkeys = state.get("hotkeys", [])
        block_at_registration = state.get("block_at_registration", [])
        
        # Build miner scores directly from state's basic data
        for i, hotkey in enumerate(hotkeys):
            if i < len(scores):
                miner_score = {
                    "validator_hotkey": validator_hotkey,
                    "miner_hotkey": hotkey,
                    "miner_uid": i,
                    "netuid": state.get("netuid", 2),
                    "evaluation_block": current_block,
                    "score": float(scores[i]) if scores[i] is not None else 0.0,
                    "registration_block": block_at_registration[i] if i < len(block_at_registration) else 0,
                    "evaluation_time": datetime.now().isoformat()
                }
                miner_scores.append(miner_score)
        
        return miner_scores
    
    async def _submit_miner_scores(self, miner_scores: list) -> None:
        """Submit miner score information to unified database"""
        # Remove empty data check, ensure always submit (even if empty list)
        try:
            headers = {}
            if self.proxy_api_token:
                headers['Authorization'] = f'Bearer {self.proxy_api_token}'
                
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.proxy_api_url}/api/validators/submit_miner_scores",
                    json={"miner_scores": miner_scores},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status == 200:
                        logging.info(f"✅ Miner score submission successful: {len(miner_scores)} records")
                    else:
                        logging.warning(f"Miner score submission failed: {response.status}")
        except Exception as e:
            logging.error(f"Failed to submit miner scores: {e}")


class RedisValidatorStorage(BaseRedisStorage):
    def __init__(self, config: Optional["Config"] = None):
        super().__init__(config)
        self.validator_id = self.generate_user_id(config)
        # Unified database API configuration - use environment variables directly
        self.proxy_api_url = os.getenv('SUBNET_PROXY_API_URL', 'http://127.0.0.1:8889')
        self.proxy_api_token = os.getenv('SUBNET_PROXY_API_TOKEN', '')
        
        # Process submit_validator_info configuration, default true
        self.submit_to_db = os.getenv('SUBMIT_VALIDATOR_INFO', 'true').lower() == 'true'
        
        # Create thread pool executor for async tasks
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="db_submit")

    def save_state(self, state: dict) -> None:
        """Save the validator state to Redis."""
        prefix = f"{self.validator_id}_state"
        self.save_data(key="current", data=state, prefix=prefix)
        
        # Additional submission to unified database - moved to main loop scheduled submission, commented out here
        # if self.submit_to_db:
        #     logging.info(f"🔄 Preparing to submit validator info to database: {self.proxy_api_url}")
        #     # Use thread pool executor to run async tasks
        #     def run_async_tasks():
        #         try:
        #             loop = asyncio.new_event_loop()
        #             asyncio.set_event_loop(loop)
        #             
        #             # Submit validator info and miner scores in parallel
        #             miner_scores = self._extract_miner_scores(state)
        #             logging.info(f"🔄 Preparing to submit miner score data: {len(miner_scores)} records")
        #             
        #             # Execute in parallel using asyncio.gather
        #             loop.run_until_complete(asyncio.gather(
        #                 self._submit_validator_info(state),
        #                 self._submit_miner_scores(miner_scores),
        #                 return_exceptions=True
        #             ))
        #             
        #         except Exception as e:
        #             logging.error(f"Async submission task failed: {e}")
        #         finally:
        #             loop.close()
        #     
        #     # Submit task using thread pool
        #     self.executor.submit(run_async_tasks)
        # else:
        #     logging.warning("⚠️ submit_to_db configured as False, skipping database submission")

    def load_latest_state(self) -> dict:
        """Get validator state for specific block."""
        prefix = f"{self.validator_id}_state"
        return self.load_data(key="current", prefix=prefix)
    
    async def _submit_validator_info(self, state: dict) -> None:
        """Submit validator information to unified database"""
        try:
            # Extract validator info from state
            validator_info = self._extract_validator_info(state)
            
            # Send to proxy API
            headers = {}
            if self.proxy_api_token:
                headers['Authorization'] = f'Bearer {self.proxy_api_token}'
                
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.proxy_api_url}/api/validators/submit_info",
                    json=validator_info,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logging.info(f"✅ ValidatorInformationSubmitSuccess: {validator_info['hotkey'][:8]}...")
                    else:
                        logging.warning(f"ValidatorInformationSubmitFailure: {response.status}")
                        
        except Exception as e:
            logging.error(f"SubmitValidatorInformationFailure: {e}")
    
    def _extract_validator_info(self, state: dict) -> dict:
        """Extract required information from validator state"""
        return {
            "hotkey": state.get("hotkey", ""),
            "coldkey": state.get("coldkey", ""),
            "uid": state.get("uid", 0),
            "netuid": state.get("netuid", 2),
            "current_block": state.get("current_block", 0),
            "validator_stake": state.get("validator_stake", 0.0),
            "last_update": state.get("last_update", 0),
            "scores": state.get("scores", []),
            "weights": state.get("weights", []),
            "timestamp": datetime.now().isoformat(),
            "validator_version": state.get("version", "unknown"),
            
            # System monitoring information
            "cpu_usage": state.get("cpu_usage", 0.0),
            "memory_usage": state.get("memory_usage", 0.0),
            "disk_usage": state.get("disk_usage", 0.0),
            "network_latency": state.get("network_latency", 0.0)
        }
    
    def _extract_miner_scores(self, state: dict) -> list:
        """Extract miner score information from validator state"""
        miner_scores = []
        
        # Get basic information
        validator_hotkey = state.get("hotkey", "")
        current_block = state.get("current_block", 0)
        scores = state.get("scores", [])
        hotkeys = state.get("hotkeys", [])
        block_at_registration = state.get("block_at_registration", [])
        
        # Build miner scores directly from state's basic data
        for i, hotkey in enumerate(hotkeys):
            if i < len(scores):
                miner_score = {
                    "validator_hotkey": validator_hotkey,
                    "miner_hotkey": hotkey,
                    "miner_uid": i,
                    "netuid": state.get("netuid", 2),
                    "evaluation_block": current_block,
                    "score": float(scores[i]) if scores[i] is not None else 0.0,
                    "registration_block": block_at_registration[i] if i < len(block_at_registration) else 0,
                    "evaluation_time": datetime.now().isoformat()
                }
                miner_scores.append(miner_score)
        
        return miner_scores
    
    async def _submit_miner_scores(self, miner_scores: list) -> None:
        """Submit miner score information to unified database"""
        # Remove empty data check, ensure always submit (even if empty list)
        try:
            headers = {}
            if self.proxy_api_token:
                headers['Authorization'] = f'Bearer {self.proxy_api_token}'
                
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.proxy_api_url}/api/validators/submit_miner_scores",
                    json={"miner_scores": miner_scores},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status == 200:
                        logging.info(f"✅ Miner score submission successful: {len(miner_scores)} records")
                    else:
                        logging.warning(f"Miner score submission failed: {response.status}")
        except Exception as e:
            logging.error(f"Failed to submit miner scores: {e}")


STORAGE_CLASSES = {"json": JsonValidatorStorage, "redis": RedisValidatorStorage}


# Factory function to get storage
def get_validator_storage(
    storage_type: str, config: "Config"
) -> Union["JsonValidatorStorage", "RedisValidatorStorage"]:
    """Get a Validator storage instance based on a passed storage type.

    Arguments:
        storage_type: The type of storage to initialize.
        config: The configuration object.

    Returns:
        Storage instance created based on the specified storage type.
    """
    if storage_type not in STORAGE_CLASSES:
        raise ValueError(f"Unknown storage type: {storage_type}")

    storage_class = STORAGE_CLASSES[storage_type]

    try:
        return storage_class(config)
    except Exception as e:
        message = f"Failed to initialize {storage_type} storage: {e}"
        logging.error(message)
        raise Exception(message)
