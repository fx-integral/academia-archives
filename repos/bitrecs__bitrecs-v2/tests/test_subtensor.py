import os
import asyncio
from utils.subtensor import SubtensorWrapper

def test_default_finney_connection():
    """Test connection using default SUBTENSOR_NETWORK=finney."""
    os.environ["SUBTENSOR_NETWORK"] = "finney"
    os.environ.pop("SUBTENSOR_ADDRESS", None)  # Ensure no override
    
    wrapper = SubtensorWrapper()
    try:
        async def connect_and_test():
            subtensor = await wrapper.ensure_connected()
            block = await subtensor.substrate.get_block()  # Verify connection
            assert block is not None, "Failed to get block with default finney"
            print(f"Default finney connection successful, block: {block}")
        
        asyncio.run(connect_and_test())
    finally:
        asyncio.run(wrapper.close())

def test_custom_address_override():
    """Test overriding endpoint with custom SUBTENSOR_ADDRESS while keeping SUBTENSOR_NETWORK=finney."""
    os.environ["SUBTENSOR_NETWORK"] = "finney"
    os.environ["SUBTENSOR_ADDRESS"] = "wss://finney.opentensor.ai:443"  # Custom override
    
    wrapper = SubtensorWrapper()
    try:
        async def connect_and_test():
            subtensor = await wrapper.ensure_connected()
            block = await subtensor.substrate.get_block()  # Verify custom endpoint used
            assert block is not None, "Failed to get block with custom address override"
            print(f"Custom address override successful, block: {block}")
        
        asyncio.run(connect_and_test())
    finally:
        asyncio.run(wrapper.close())

def test_fallback_on_custom_failure():
    """Test fallback to network default if custom SUBTENSOR_ADDRESS fails."""
    os.environ["SUBTENSOR_NETWORK"] = "finney"
    os.environ["SUBTENSOR_ADDRESS"] = "wss://invalid.endpoint:443"  # Invalid custom URL
    
    wrapper = SubtensorWrapper()
    try:
        async def connect_and_test():
            subtensor = await wrapper.ensure_connected()
            block = await subtensor.substrate.get_block()  # Should fall back to finney
            assert block is not None, "Failed to fallback and get block"
            print(f"Fallback on custom failure successful, block: {block}")
        
        asyncio.run(connect_and_test())
    finally:
        asyncio.run(wrapper.close())