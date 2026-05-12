import pytest
import secrets
from datetime import datetime, timezone
from uuid import UUID
from models.inference_report import InferenceReport
from queries.banned_hotkey import add_banned_hotkey
from queries.evaluation import get_num_total_screener_2_evaluations_for_agent_id
from queries.inference import insert_inference
from queries.system_enabled import get_system_enabled
from utils.database import check_database_health
from queries.session import insert_validator_session

@pytest.mark.asyncio
@pytest.mark.usefixtures("db_setup")
async def test_db_health():
    is_healthy = await check_database_health()
    assert is_healthy is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("db_setup")
async def test_insert_session():
    session_id = secrets.token_hex(8)
    name = "test_node"
    hotkey = "test_hotkey"
    ip = "127.0.0.1"
    inserted_session_id = await insert_validator_session(session_id, name, hotkey, ip)
    assert inserted_session_id > 0
    

@pytest.mark.asyncio
@pytest.mark.usefixtures("db_setup")
async def test_is_system_enabled():
    enabled = await get_system_enabled()
    print(f"System enabled status: {enabled}")
    assert isinstance(enabled, bool), "Expected a boolean value for system enabled status"


@pytest.mark.asyncio
@pytest.mark.usefixtures("db_setup")
async def test_get_current_agents():
    from queries.agent import get_current_agents
    agents = await get_current_agents()
    assert isinstance(agents, list), "Expected a list of agents to be returned"
    #agents = sorted(agents, key=lambda x: x.created_at, reverse=True)
    for agent in agents:
        print(f"{agent.name} - Agent ID: {agent.agent_id}, Miner Hotkey: {agent.miner_hotkey}, Status: {agent.status}")
        assert agent.system_prompt_template == '', "Expected system_prompt_template to be null"
        assert agent.user_prompt_template == '', "Expected user_prompt_template to be null"

    print(f"Total agents retrieved: {len(agents)}")


@pytest.mark.asyncio
@pytest.mark.usefixtures("db_setup")
async def test_insert_inference_report():
    run_id = UUID("00054fc0-8a1e-4ff1-bda2-661c0b24287f")
    report = InferenceReport(
        evaluation_run_id=run_id,
        provider="test_provider",
        model="test_model",
        temperature=0.5,
        messages=[{"role": "user", "content": "Hello, world!"}],
        status_code=200,
        response="Hello, user!",
        num_input_tokens=5,
        num_output_tokens=4,
        cost_usd=0.001,
        response_sent_at=datetime.now(timezone.utc),
        request_received_at=datetime.now(timezone.utc)
    )
    inference_id = await insert_inference(
        evaluation_run_id=report.evaluation_run_id,
        provider=report.provider,
        model=report.model,
        temperature=report.temperature,
        messages=report.messages,
        status_code=report.status_code,
        response=report.response,
        num_input_tokens=report.num_input_tokens,
        num_output_tokens=report.num_output_tokens,
        cost_usd=report.cost_usd,
        response_sent_at=report.response_sent_at,
        request_received_at=report.request_received_at        
    )
    assert inference_id is not None, "Expected a valid inference ID to be returned after insertion"


@pytest.mark.asyncio
@pytest.mark.usefixtures("db_setup")
async def test_add_banned_hotkey():
    from queries.banned_hotkey import add_banned_hotkey, get_banned_hotkey
    miner_hotkey = "test_banned_hotkey"
    banned_reason = "Testing ban functionality"
    banned_hotkey = await add_banned_hotkey(miner_hotkey, banned_reason)
    assert banned_hotkey is True, "Expected the banned hotkey to be added successfully"    

    # Verify that the banned hotkey can be retrieved
    retrieved_hotkey = await get_banned_hotkey(miner_hotkey)
    assert retrieved_hotkey is not None, "Expected to retrieve the banned hotkey after insertion"
    assert retrieved_hotkey.miner_hotkey == miner_hotkey, "Expected the retrieved miner hotkey to match the input value"
    assert retrieved_hotkey.banned_reason == banned_reason, "Expected the retrieved banned reason to match the input value"
    

@pytest.mark.asyncio
@pytest.mark.usefixtures("db_setup")
async def test_load_banned_hotkeys():
    t = ['5FCh2LAXpRWzf93Ekx7pqUmokG8BHH16dX6AxJV3ptGJzPr6', '5FNL6e4JsB3ZPUGk1x1izK1xnTWsZDZrVF6WaRp1gNpoTvsM', '5ChvSkb7Gfy7pypH5Cxo9QP2DMEJ88kwFnZvnCwESD66KVzD', '5C8KiUpE5SYwsAX1pPDbqKdLFDhGeE6JpAN4DHcYfwwvShAF', '5FGvuwULd6y5Y9L18eNEuD6M2iLF1Zst7TUwNfmJUcziiiJt', ]
    count = 0
    for hotkey in t:
        banned_reason = "Testing bulk ban functionality"
        banned_hotkey = await add_banned_hotkey(hotkey, banned_reason)
        assert banned_hotkey is True, f"Expected the hotkey {hotkey} to be added to the ban list successfully"
        count += 1
        if count > 5:
            break
    print(f"Successfully added {count} hotkeys to the ban list")


@pytest.mark.asyncio
@pytest.mark.usefixtures("db_setup")
async def test_max_screener_2_attempts():
    agent_id = "4672b021-9eaa-4a4b-808c-233da0b0e11e"
    result = await get_num_total_screener_2_evaluations_for_agent_id(agent_id)
    print(f"Total Screener 2 evaluations for agent {agent_id}: {result}")
    assert isinstance(result, int), "Expected the result to be an integer representing the total number of Screener 2 evaluations for the agent"
    
    