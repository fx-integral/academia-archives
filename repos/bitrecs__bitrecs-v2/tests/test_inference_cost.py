import os
import httpx
import pytest
import time  # Add this import
from unittest.mock import patch
from datetime import datetime
from api.endpoints.validator_models import InferenceCostEstimateRequest
from utils.inference_coster import InferenceCoster, CostResult

@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the shared cache before each test to ensure isolation."""
    InferenceCoster._cache.clear()
    yield

@pytest.mark.asyncio
async def test_fetch_cost_chutes_success():
    """Test fetching cost for Chutes provider with a successful API response."""
    coster = InferenceCoster("chutes", "test-model")
    
    mock_data = {
        "items": [
            {
                "name": "test-model",
                "current_estimated_price": {
                    "per_million_tokens": {
                        "input": {"usd": 0.5},
                        "output": {"usd": 1.0}
                    }
                }
            }
        ]
    }
    
    with patch.object(coster, '_fetch_chutes_data', return_value=mock_data) as mock_fetch:
        result = await coster.fetch_cost()
        assert result == CostResult(input=0.5, output=1.0)
        mock_fetch.assert_called_once()

@pytest.mark.asyncio
async def test_fetch_cost_openrouter_success():
    """Test fetching cost for OpenRouter provider with a successful API response."""
    coster = InferenceCoster("open_router", "test-model")
    
    mock_data = {
        "data": [
            {
                "id": "test-model",
                "pricing": {
                    "prompt": "0.0000005",  # 0.5 per million
                    "completion": "0.000001"  # 1.0 per million
                }
            }
        ]
    }
    
    with patch.object(coster, '_fetch_openrouter_data', return_value=mock_data) as mock_fetch:
        result = await coster.fetch_cost()
        assert result == CostResult(input=0.5, output=1.0)
        mock_fetch.assert_called_once()

@pytest.mark.asyncio
async def test_fetch_cost_chutes_model_not_found():
    """Test fetching cost for Chutes when model is not found."""
    coster = InferenceCoster("chutes", "unknown-model")
    
    mock_data = {"items": []}
    
    with patch.object(coster, '_fetch_chutes_data', return_value=mock_data):
        result = await coster.fetch_cost()
        assert result is None

@pytest.mark.asyncio
async def test_fetch_cost_openrouter_model_not_found():
    """Test fetching cost for OpenRouter when model is not found."""
    coster = InferenceCoster("open_router", "unknown-model")
    
    mock_data = {"data": []}
    
    with patch.object(coster, '_fetch_openrouter_data', return_value=mock_data):
        result = await coster.fetch_cost()
        assert result is None

@pytest.mark.asyncio
async def test_fetch_cost_invalid_provider():
    """Test that invalid provider raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported provider"):
        coster = InferenceCoster("invalid", "test-model")
        # No need to call fetch_cost since __init__ raises

@pytest.mark.asyncio
async def test_calculate_cost_success():
    """Test calculating total cost with valid pricing."""
    coster = InferenceCoster("chutes", "test-model")
    
    with patch.object(coster, 'fetch_cost', return_value=CostResult(input=0.5, output=1.0)) as mock_fetch:
        result = await coster.calculate_cost(1000000, 2000000)  # 1M input, 2M output
        assert result == 2.5  # (1*0.5) + (2*1.0)
        mock_fetch.assert_called_once()

@pytest.mark.asyncio
async def test_calculate_cost_no_pricing():
    """Test calculating cost when pricing is unavailable."""
    coster = InferenceCoster("chutes", "test-model")
    
    with patch.object(coster, 'fetch_cost', return_value=None):
        result = await coster.calculate_cost(1000000, 2000000)
        assert result is None

@pytest.mark.asyncio
async def test_caching():
    """Test that caching works and prevents repeated fetches within TTL."""
    coster = InferenceCoster("chutes", "test-model")
    
    mock_data = {
        "items": [
            {
                "name": "test-model",
                "current_estimated_price": {
                    "per_million_tokens": {
                        "input": {"usd": 0.5},
                        "output": {"usd": 1.0}
                    }
                }
            }
        ]
    }
    
    with patch.object(coster, '_fetch_chutes_data', return_value=mock_data) as mock_fetch:
        # First call
        result1 = await coster.fetch_cost()
        assert result1 == CostResult(input=0.5, output=1.0)
        
        # Second call should use cache
        result2 = await coster.fetch_cost()
        assert result2 == CostResult(input=0.5, output=1.0)
        
        # Should only be called once due to caching
        mock_fetch.assert_called_once()

@pytest.mark.asyncio
async def test_cache_expiration():
    """Test that cache expires after TTL and refetches."""
    coster = InferenceCoster("chutes", "test-model")
    
    mock_data = {
        "items": [
            {
                "name": "test-model",
                "current_estimated_price": {
                    "per_million_tokens": {
                        "input": {"usd": 0.5},
                        "output": {"usd": 1.0}
                    }
                }
            }
        ]
    }
    
    with patch.object(coster, '_fetch_chutes_data', return_value=mock_data) as mock_fetch, \
         patch('utils.inference_coster.datetime') as mock_datetime:
        
        # Set initial time
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        
        # First call
        result1 = await coster.fetch_cost()
        assert result1 == CostResult(input=0.5, output=1.0)
        
        # Advance time past TTL (45 min)
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 46, 0)
        
        # Second call should refetch
        result2 = await coster.fetch_cost()
        assert result2 == CostResult(input=0.5, output=1.0)
        
        # Should be called twice
        assert mock_fetch.call_count == 2

@pytest.mark.asyncio
async def test_init_invalid_provider():
    """Test that invalid provider raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported provider"):
        InferenceCoster("invalid", "test-model")


@pytest.mark.asyncio
async def test_chutes_valid_model():
    """Test fetching cost for a valid Chutes model (real-world use case)."""
    coster = InferenceCoster("chutes", "Qwen/Qwen3-32B")
    
    # Mock data with the expected model
    mock_data = {
        "items": [
            {
                "name": "Qwen/Qwen3-32B",
                "current_estimated_price": {
                    "per_million_tokens": {
                        "input": {"usd": 0.08},
                        "output": {"usd": 0.24}
                    }
                }
            }
        ]
    }
    
    with patch.object(coster, '_fetch_chutes_data', return_value=mock_data):
        result = await coster.fetch_cost()
        assert result.input == pytest.approx(0.08, rel=0.1)
        assert result.output == pytest.approx(0.24, rel=0.1)

@pytest.mark.asyncio
async def test_open_router_valid_model():
    """Test fetching cost for a valid OpenRouter model (real-world use case)."""
    coster = InferenceCoster("open_router", "qwen/qwen3.5-9b")
    
    # Mock data with the expected model
    mock_data = {
        "data": [
            {
                "id": "qwen/qwen3.5-9b",
                "pricing": {
                    "prompt": "0.00000005",  # 0.05 per million
                    "completion": "0.00000015"  # 0.15 per million
                }
            }
        ]
    }
    
    with patch.object(coster, '_fetch_openrouter_data', return_value=mock_data):
        result = await coster.fetch_cost()
        assert result.input == pytest.approx(0.05, rel=0.1)
        assert result.output == pytest.approx(0.15, rel=0.1)


@pytest.mark.asyncio
async def test_open_router_get_cost_estimate_api_ok():
    
    base_url = os.getenv("BITRECS_PLATFORM_URL")
    #base_url = "http://localhost:8000" 

    key = os.environ.get("BITRECS_PLATFORM_API_KEY")
    headers = {"X-API-Key": key}
    estimate = InferenceCostEstimateRequest(
        provider="open_router",
        model_name="qwen/qwen3.5-9b",
        input_tokens=1_000_000,
        output_tokens=1_000_000
    )
    with httpx.Client() as client:
        response = client.post(
            f"{base_url}/inference/estimate-cost",
            headers=headers,
            json=estimate.model_dump()            
        )
        assert response.status_code == 200
        result = response.json()
        print(result)
        assert "input_cost" in result
        assert "output_cost" in result
        assert "total_cost" in result
        assert result["input_cost"] == pytest.approx(0.05, rel=0.1)
        assert result["output_cost"] == pytest.approx(0.15, rel=0.1)
        assert result["total_cost"] == pytest.approx(0.20, rel=0.1)
        
    


@pytest.mark.asyncio
async def test_chutesr_get_cost_estimate_api_ok():
    
    base_url = os.getenv("BITRECS_PLATFORM_URL")
    #base_url = "http://localhost:8000" 

    key = os.environ.get("BITRECS_PLATFORM_API_KEY")
    headers = {"X-API-Key": key}
    estimate = InferenceCostEstimateRequest(
        provider="chutes",
        model_name="unsloth/Mistral-Nemo-Instruct-2407",
        input_tokens=1_000_000,
        output_tokens=1_000_000
    )
    with httpx.Client() as client:
        response = client.post(
            f"{base_url}/inference/estimate-cost",
            headers=headers,
            json=estimate.model_dump()            
        )
        assert response.status_code == 200
        result = response.json()
        print(result)
        assert "input_cost" in result
        assert "output_cost" in result
        assert "total_cost" in result
        assert result["input_cost"] == pytest.approx(0.02, rel=0.1)
        assert result["output_cost"] == pytest.approx(0.04, rel=0.1)
        assert result["total_cost"] == pytest.approx(0.06, rel=0.1)



def test_get_agent_cost_report():
    """Test GET /inference/cost endpoint"""
    #SERVICE_URL = "http://localhost:8000"  
    SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "http://localhost:8000")

    key = os.environ.get("BITRECS_PLATFORM_API_KEY")
    headers = {"X-API-Key": key}  
    agent_id = "24cbbac5-b00d-452b-b966-391fa88e5632"

    url = f"{SERVICE_URL}/inference/cost?agent_id={agent_id}"
    with httpx.Client() as client:
        response = client.get(
            url=url,            
            headers=headers,            
        )    
        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
        result = response.json()
        assert "agent_id" in result, "Response should contain agent_id"
        assert "inference_cost_report" in result, "Response should contain inference_cost_report"
        print(f"Inference cost report for agent {result['agent_id']}: {result['inference_cost_report']}")

        run_cost = sum(item.get("cost_usd", 0) for item in result["inference_cost_report"])
        print(f"Total inference cost for agent {result['agent_id']}: ${run_cost:.4f}")
        total_input_tokens = sum(item.get("num_input_tokens", 0) for item in result["inference_cost_report"])
        total_output_tokens = sum(item.get("num_output_tokens", 0) for item in result["inference_cost_report"])
        print(f"Total input tokens: {total_input_tokens}, Total output tokens: {total_output_tokens}")
        total_tokens = total_input_tokens + total_output_tokens
        print(f"\033[1;32mTotal tokens: {total_tokens} for cost of ${run_cost:.8f}\033[0m")


@pytest.mark.asyncio
async def test_chutes_no_model_found():    
    base_url = os.getenv("BITRECS_PLATFORM_URL")
    base_url = "http://localhost:8000" 
    key = os.environ.get("BITRECS_PLATFORM_API_KEY")
    headers = {"X-API-Key": key}
    estimate = InferenceCostEstimateRequest(
        provider="chutes",
        model_name="unsloth/Mistral-Nemo-Instruct-2407_invalid",
        input_tokens=1_000_000,
        output_tokens=1_000_000
    )
    with httpx.Client() as client:
        response = client.post(
            f"{base_url}/inference/estimate-cost",
            headers=headers,
            json=estimate.model_dump()            
        )
        assert response.status_code == 200
        result = response.json()
        print(result)
        assert "input_cost" in result
        assert "output_cost" in result
        assert "total_cost" in result
        assert result["input_cost"] == 0.0
        assert result["output_cost"] == 0.0
        assert result["total_cost"] == 0.0

    