import os
import json
import httpx
import textwrap
import utils.logger as logger
import validator.config as config
from typing import Any
from pydantic import BaseModel

HTTP_TIMEOUT_SECONDS = 120

def _pretty_print_httpx_error(method: str, url: str, e: httpx.HTTPStatusError):    
    logger.error(f"HTTP {e.response.status_code} {e.response.reason_phrase} during {method} {url}")    
    try:
        response_json = e.response.json()
        if isinstance(response_json, dict) and len(response_json) == 1 and "detail" in response_json and isinstance(response_json["detail"], str):            
            logger.error(textwrap.indent(response_json["detail"], "  "))
        else:            
            logger.error(f"Response (JSON):")
            logger.error(textwrap.indent(json.dumps(response_json, indent=2), "  "))
    except Exception:        
        logger.error(f"Response:")
        logger.error(textwrap.indent(e.response.text, "  "))


async def get_bitrecs_platform(endpoint: str, *, quiet: int = 0) -> Any:
    url = f"{config.BITRECS_PLATFORM_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    if quiet <= 1:
        logger.debug(f"Sending request for GET {url}")
    try:
        x_api_key = os.environ.get("BITRECS_PLATFORM_API_KEY")
        headers = {"Content-Type": "application/json", "X-API-Key": x_api_key}
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            response_json = response.json()
            if quiet <= 1:
                logger.debug(f"Received response for GET {url}: {response.status_code} {response.reason_phrase}")
            if response_json != {} and quiet == 0:
                logger.debug(textwrap.indent(json.dumps(response_json, indent=2), "  "))            
            return response.json()    
    except httpx.HTTPStatusError as e:
        _pretty_print_httpx_error("GET", url, e)        
        raise
    
    except Exception as e:        
        logger.error(f"{type(e).__name__} during GET {url}")
        raise


async def post_bitrecs_platform(endpoint: str, body: BaseModel, *, bearer_token: str = None, quiet: int = 0) -> Any:
    url = f"{config.BITRECS_PLATFORM_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    body_dict = body.model_dump(mode="json")
    if quiet <= 1:
        logger.debug(f"Sending request for POST {url}")
    if body_dict != {} and quiet == 0:
        logger.debug(textwrap.indent(json.dumps(body_dict, indent=2), "  "))
    
    try:    
        x_api_key = os.environ.get("BITRECS_PLATFORM_API_KEY")
        headers = {"Content-Type": "application/json", "X-API-Key": x_api_key}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=body_dict, headers=headers)
            response.raise_for_status()
            response_json = response.json()
            if quiet <= 1:
                logger.debug(f"Received response for POST {url}: {response.status_code} {response.reason_phrase}")
            if response_json != {} and quiet == 0:
                logger.debug(textwrap.indent(json.dumps(response_json, indent=2), "  "))            
            return response.json()
    except httpx.HTTPStatusError as e:
        _pretty_print_httpx_error("POST", url, e)
        raise
    
    except Exception as e:
        logger.error(f"{type(e).__name__} during POST {url}")
        raise