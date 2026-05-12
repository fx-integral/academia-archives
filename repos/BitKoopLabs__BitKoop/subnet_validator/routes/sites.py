from typing import Annotated, Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from fiber.logging_utils import get_logger

from ..dependencies import get_site_service
from ..services.site_service import SiteService


logger = get_logger(__name__)

router = APIRouter()


@router.get("/")
async def get_sites(
    site_service: Annotated[
        SiteService,
        Depends(get_site_service),
    ],
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(
        20, ge=1, le=100, description="Number of sites per page"
    ),
):
    """
    Get paginated list of all sites with slot information.
    """
    try:
        sites_data = site_service.get_sites_paginated(
            page=page, page_size=page_size
        )
        return sites_data
    except Exception as e:
        logger.error(f"Failed to get sites: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get sites: {e}"
        )


@router.get("/{site_id}")
async def get_site_info(
    site_id: int,
    site_service: Annotated[
        SiteService,
        Depends(get_site_service),
    ],
):
    """
    Get site information including available slots for coupon submission.
    """
    try:
        site = site_service.get_site_with_slots(site_id)
        if not site:
            raise HTTPException(
                status_code=404, detail=f"Site with id {site_id} not found"
            )

        return {
            "id": site.id,
            "base_url": site.base_url,
            "status": site.status,
            "miner_hotkey": site.miner_hotkey,
            "api_url": site.api_url,
            "total_coupon_slots": site.total_coupon_slots,
            "available_slots": site.available_slots,
            "can_submit_coupon": site.available_slots > 0,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get site info for site {site_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get site info: {e}"
        )
