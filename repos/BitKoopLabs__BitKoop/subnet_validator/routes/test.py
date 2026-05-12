from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
)
from pydantic import (
    BaseModel,
)
import json
import os
from typing import Annotated
from subnet_validator.services.dynamic_config_service import (
    DynamicConfigService,
)
from subnet_validator.dependencies import get_dynamic_config_service

router = APIRouter()

CONFIG_PATH = "data/config.json"


class ProbabilityUpdateRequest(BaseModel):
    probability: float


@router.get("/config")
async def get_config():
    try:
        with open(
            CONFIG_PATH,
            "r",
        ) as f:
            config = json.load(f)
        return config
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read config: {e}",
        )


@router.post("/config/site/{site_id}/probability")
async def set_site_probability(
    site_id: int,
    req: ProbabilityUpdateRequest,
):
    try:
        with open(
            CONFIG_PATH,
            "r",
        ) as f:
            config = json.load(f)
        sites = config.setdefault(
            "sites",
            {},
        )
        site_cfg = sites.setdefault(
            str(site_id),
            {},
        )
        site_cfg["valid_coupon_probability"] = req.probability
        with open(
            CONFIG_PATH,
            "w",
        ) as f:
            json.dump(
                config,
                f,
                indent=4,
            )
        return {
            "site_id": site_id,
            "valid_coupon_probability": req.probability,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update config: {e}",
        )


@router.get("/sync/status")
async def get_sync_status(
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
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read sync status: {e}",
        )
