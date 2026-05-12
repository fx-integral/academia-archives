import asyncio
import datetime
from pydantic import BaseModel
from utils.ttl import ttl_cache
from typing import List
from fastapi import APIRouter, HTTPException, Request
from queries.evaluation_set import get_latest_set_id, get_set_created_at
from queries.problem_statistics import ProblemStatistics, get_problem_statistics
from api.utils.limiter import limiter

EARLIEST_SET_ID_WITH_GOOD_DATA = 0 

router = APIRouter()

# /statistics/problem-statistics?set_id=
class ProblemStatisticsResponse(BaseModel):
    problem_stats: List[ProblemStatistics]
    problem_set_id: int
    problem_set_created_at: datetime.datetime

@router.get("/problem-statistics")
@limiter.limit("60/minute")
@ttl_cache(ttl_seconds=15*60) # 15 mins
async def problem_statistics(request: Request, set_id: int) -> ProblemStatisticsResponse:
    max_problem_set_id = await get_latest_set_id()

    if set_id is None or set_id < 1:
       raise HTTPException(status_code=400, detail="set_id query parameter is required.")
    
    if set_id > max_problem_set_id:
        raise HTTPException(status_code=400, detail=f"set_id {set_id} is greater than the latest available set_id {max_problem_set_id}.")
    
    problem_stats, problem_set_created_at = await asyncio.gather(
        get_problem_statistics(set_id),
        get_set_created_at(set_id)
    )
    
    return ProblemStatisticsResponse(
        problem_stats=problem_stats,
        problem_set_id=set_id,
        problem_set_created_at=problem_set_created_at
    )
