import os
import asyncio
import httpx
import logging
import pytest
from datetime import datetime, timezone
from models.agent import Agent
from rules.agent_validator import validate_artifact_template
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

SERVICE_URL = "http://localhost:8000"
client = httpx.Client(base_url=SERVICE_URL)


def test_get_root():
    response = client.get("/")    
    logger.info("Root endpoint response: %s", response.json())    
    result = response.json()
    assert response.status_code == 200
    assert "Bitrecs V2 Testnet" in result["message"]
    assert "network" in result
    
def test_get_health():
    response = client.get("/health")
    logger.info("Health endpoint response: %s", response.json())
    result = response.json()
    assert response.status_code == 200
    assert result["status"] == "healthy"
    assert result["message"] == "OK"
    assert result["db_status"] == "OK"

def test_template_validation_fails_ok():
    """Test submitting an artifact via POST /artifact."""
    sample_artifact = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "miner_hotkey": "test_hotkey",
        "miner_uid": "123",
        "provider": "test_provider",
        "model": "test_model",
        "system_prompt_template": "System prompt Unit Test",
        "user_prompt_template": "User prompt Unit Test",
        "sampling_params": {"temperature": 0.7},
        "fewshot_examples": [{"role": "user", "content": "Hello"}],
        "eval_scores": {"accuracy": 0.95},
        "version_num": 1,
        "status": "screening_1",
        "name": "Test Artifact Unit Test",
        "ip_address": "127.0.0.1"  
    }
    validated, reason = validate_artifact_template(Agent(**sample_artifact))
    assert validated == False, "Artifact validation should fail due to invalid vars"


@pytest.mark.asyncio
async def test_health_rate_limit_simple():    
    base_url = SERVICE_URL
    async with httpx.AsyncClient() as client:
        for i in range(31):
            response = await client.get(f"{base_url}/health")
            if response.status_code == 429:
                print(f"Request {i+1}: 429 - Rate limiting detected. Test passed!")
                assert True
                return
            print(f"Request {i+1}: {response.status_code}")
            await asyncio.sleep(0.1)
        # If we reach here, all 30 succeeded without 429
        print("All 30 requests succeeded without rate limit. Test failed!")
        assert False, "Rate limiting not triggered within 30 requests"


def test_api_auth():
    """Test that API key authentication works for protected endpoints"""
    base_url = SERVICE_URL
    key = os.environ.get("BITRECS_PLATFORM_API_KEY")
    headers = {"X-API-Key": key}  

    # Test a protected endpoint (e.g., /dashboard/)
    response = client.get(f"{base_url}/dashboard/", headers=headers)
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"

    # Test with an invalid API key
    invalid_headers = {"X-API-Key": "invalid_key"}
    response_invalid = client.get(f"{base_url}/dashboard/", headers=invalid_headers)
    assert response_invalid.status_code == 401, f"Expected 401 Unauthorized, got {response_invalid.status_code}"

    # Test without an API key
    response_no_key = client.get(f"{base_url}/dashboard/")
    assert response_no_key.status_code == 401, f"Expected 401 Unauthorized, got {response_no_key.status_code}"

    # Test excluded paths that should not require authentication
    response_root = client.get(f"{base_url}/")
    assert response_root.status_code == 200, f"Expected 200 OK for root endpoint, got {response_root.status_code}"



def test_get_current_agents():
    """Test GET /retrieval/current-agents endpoint"""
    #SERVICE_URL = "http://localhost:8000"
    SERVICE_URL = os.environ.get("BITRECS_PLATFORM_URL", "http://localhost:8000")
    key = os.environ.get("BITRECS_PLATFORM_API_KEY")
    headers = {"X-API-Key": key}  
    response = client.get(f"{SERVICE_URL}/retrieval/current-agents", headers=headers)
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
    agents = response.json()
    print(agents)
    assert isinstance(agents, list), "Response should be a list of agents"
    if agents:
        agent = agents[0]
        assert "agent_id" in agent, "Agent should have an agent_id"
        assert "name" in agent, "Agent should have a name"
        assert "status" in agent, "Agent should have a status"
    print(f" found {len(agents)} agents in response")


    
  