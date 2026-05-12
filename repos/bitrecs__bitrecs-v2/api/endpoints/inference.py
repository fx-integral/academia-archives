from fastapi import APIRouter, Depends, HTTPException, Request, logger
from api.endpoints.validator import Validator, get_request_validator_with_lock
from api.endpoints.validator_models import InferenceCostEstimateRequest
from llm.llm_provider import LLM
from models.inference_report import InferenceReport
from queries.inference import get_cost_report_for_agent, insert_inference
from api.utils.limiter import limiter
from utils.inference_coster import InferenceCoster
import utils.logger as logger

router = APIRouter()

def get_inference_coster(provider: str, model_name: str) -> InferenceCoster:
    return InferenceCoster(provider, model_name)


# /inference/estimate-cost
@router.post("/estimate-cost")
@limiter.limit("120/minute")
async def estimate_inference_cost(   
    request: Request,
    inference_request: InferenceCostEstimateRequest
) -> dict:
    coster = get_inference_coster(inference_request.provider, inference_request.model_name)
    cost = await coster.cost_estimate(inference_request.input_tokens, inference_request.output_tokens)
    if cost is None:
        #raise HTTPException(status_code=503, detail="Cost estimation not available")
        logger.warning(f"Cost estimation not available for provider {inference_request.provider} and model {inference_request.model_name}")
        return {
            "input_cost": 0.0,
            "output_cost": 0.0,
            "total_cost": 0.0,
            "currency": "USD"
        }
    return {
        "input_cost": cost.input,
        "output_cost": cost.output,
        "total_cost": cost.input + cost.output,
        "currency": "USD"
    }


# /inference/report-cost
@router.post("/report-cost")
@limiter.limit("120/minute")
async def report_inference_run(
    request: Request,
    inference_report: InferenceReport,  
    validator: Validator = Depends(get_request_validator_with_lock)) -> dict:   
    try:
        inference_id = await insert_inference(
            evaluation_run_id=inference_report.evaluation_run_id,
            provider=inference_report.provider,
            model=inference_report.model,
            temperature=inference_report.temperature,
            messages=inference_report.messages,
            status_code=inference_report.status_code,
            response=inference_report.response,
            num_input_tokens=inference_report.num_input_tokens,
            num_output_tokens=inference_report.num_output_tokens,
            cost_usd=inference_report.cost_usd,
            response_sent_at=inference_report.response_sent_at
        )
        return {"inference_id": inference_id, "status": "reported"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to report inference: {str(e)}")


# /inference/cost
@router.get("/cost")
@limiter.limit("120/minute")
async def get_agent_inference_cost(request: Request, agent_id: str) -> dict:
    try:
        report = await get_cost_report_for_agent(agent_id)
        return {"agent_id": agent_id, "inference_cost_report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve inference cost report: {str(e)}")


#/inference/models
@router.get("/models")
@limiter.limit("120/minute")
async def list_available_models(request: Request) -> dict:
    try:
        coster = get_inference_coster(LLM.CHUTES.name, "")
        models = await coster.models()
        if models is None:
            raise HTTPException(status_code=503, detail="Failed to retrieve available models")        
        
        fields_to_keep = ["chute_id", "name", "tagline", "public", "slug", "version", "created_at", "updated_at", "current_estimated_price", "hot"]
        filtered_items = [
            {field: item.get(field) for field in fields_to_keep}
            for item in models.get("items", [])
        ]
        filtered_models = {"items": filtered_items}
        filtered_models["items"] = [model for model in filtered_models["items"] if model.get("public") and model.get("hot")]
        return {"models": filtered_models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve available models: {str(e)}")
