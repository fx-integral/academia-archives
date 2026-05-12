from uuid import UUID
from models.agent import Agent
from fastapi import APIRouter, HTTPException, Request
from models.miner_submission import GistInfo
from queries.agent import get_agent_by_evaluation_run_id
from queries.hotkey_gist import get_gist_info_from_agent_id
from api.utils.limiter import limiter

router = APIRouter()

# /agent/get-by-evaluation-run-id?evaluation_run_id=
@router.get("/get-by-evaluation-run-id")
@limiter.limit("60/minute")
async def agent_get_by_evaluation_run_id(request: Request, evaluation_run_id: UUID) -> Agent:
    agent = await get_agent_by_evaluation_run_id(evaluation_run_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent with evaluation run ID {evaluation_run_id} does not exist.")
    return agent

# /agent/get-gist-info?agent_id=
@router.get("/get-gist-info")
@limiter.limit("60/minute")
async def agent_get_gist_info(request: Request, agent_id: UUID) -> GistInfo:
     gist_info = await get_gist_info_from_agent_id(agent_id)
     if gist_info is None:
         raise HTTPException(status_code=404, detail=f"Gist info for agent ID {agent_id} does not exist.")
     return gist_info