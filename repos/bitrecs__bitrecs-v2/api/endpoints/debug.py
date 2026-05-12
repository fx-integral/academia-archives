from fastapi import APIRouter, Request
from utils.database import get_debug_query_info
from utils.debug_lock import get_debug_lock_info
from api.utils.limiter import limiter

router = APIRouter()

# /debug/lock-info
@router.get("/lock-info")
@limiter.limit("60/minute")
async def debug_lock_info(request: Request):
    return get_debug_lock_info()


# /debug/query-info
@router.get("/query-info")
@limiter.limit("60/minute")
async def debug_query_info(request: Request):
    return get_debug_query_info()