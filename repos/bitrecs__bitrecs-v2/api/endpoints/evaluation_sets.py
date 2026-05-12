from typing import List
from fastapi import APIRouter, Request
from models.evaluation_set import EvaluationSetProblem
from queries.evaluation_set import get_latest_set_id, get_all_evaluation_set_problems_for_set_id
from api.utils.limiter import limiter
    
router = APIRouter()

# /evaluation-sets/all-latest-set-problems
@router.get("/all-latest-set-problems")
@limiter.limit("60/minute")
async def evaluation_sets_all_latest_set_problems(request: Request) -> List[EvaluationSetProblem]:
    return await get_all_evaluation_set_problems_for_set_id(await get_latest_set_id())
