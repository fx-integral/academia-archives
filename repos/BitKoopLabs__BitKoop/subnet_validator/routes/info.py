from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from fiber.logging_utils import get_logger

from ..dependencies import get_dynamic_config_service
from ..services.dynamic_config_service import DynamicConfigService


logger = get_logger(__name__)

router = APIRouter()


@router.get("/sync")
async def get_sync_info(
    dynamic_config_service: Annotated[
        DynamicConfigService,
        Depends(get_dynamic_config_service),
    ],
):
    try:
        progress = dynamic_config_service.get_sync_progress()
        last_result = dynamic_config_service.get_last_sync_result()
        return {
            "progress": progress or None,
            "last_result": last_result or None,
        }
    except Exception as e:
        logger.error(f"Failed to read sync info: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to read sync info: {e}"
        )
