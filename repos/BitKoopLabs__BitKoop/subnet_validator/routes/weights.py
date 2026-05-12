from typing import (
    Annotated,
    Dict,
)
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import (
    BaseModel,
)

from ..dependencies import (
    get_weight_calculator_service,
)
from ..services.weight_calculator_service import (
    WeightCalculatorService,
)
from fiber.logging_utils import (
    get_logger,
)

logger = get_logger(__name__)

router = APIRouter()


class WeightCalculationResponse(BaseModel):
    scores: Dict[str, float]
    total_miners: int
    max_score: float
    min_score: float
    average_score: float


@router.get("/calculate", response_model=WeightCalculationResponse)
async def calculate_weights(
    weight_calculator: Annotated[
        WeightCalculatorService,
        Depends(get_weight_calculator_service),
    ],
) -> WeightCalculationResponse:
    """
    Calculate weights for all miners based on their coupon and container performance.
    """
    try:
        logger.info("API request to calculate weights")

        # Calculate weights using the service
        scores = weight_calculator.calculate_weights()

        if not scores:
            return WeightCalculationResponse(
                scores={},
                total_miners=0,
                max_score=0.0,
                min_score=0.0,
                average_score=0.0,
            )

        # Calculate statistics
        total_miners = len(scores)
        max_score = max(scores.values())
        min_score = min(scores.values())
        average_score = sum(scores.values()) / total_miners

        return WeightCalculationResponse(
            scores=scores,
            total_miners=total_miners,
            max_score=max_score,
            min_score=min_score,
            average_score=average_score,
        )

    except Exception as e:
        logger.error(f"Error calculating weights via API: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate weights: {str(e)}",
        )


@router.get("/scores")
async def get_weights(
    weight_calculator: Annotated[
        WeightCalculatorService,
        Depends(get_weight_calculator_service),
    ],
) -> Dict[str, float]:
    """
    Get current weight scores for all miners.
    This endpoint returns the raw scores without additional statistics.
    """
    try:
        logger.info("API request to get weight scores")

        # Calculate weights using the service
        scores = weight_calculator.calculate_weights()

        return scores

    except Exception as e:
        logger.error(f"Error getting weights via API: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get weights: {str(e)}",
        )
