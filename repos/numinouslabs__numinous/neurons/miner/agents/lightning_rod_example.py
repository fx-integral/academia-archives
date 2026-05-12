import asyncio
import os
import re
import time
from datetime import datetime

import httpx
from pydantic import BaseModel

RUN_ID = os.getenv("RUN_ID")
if not RUN_ID:
    raise ValueError("RUN_ID environment variable is required but not set")

PROXY_URL = os.getenv("SANDBOX_PROXY_URL", "http://sandbox_proxy")
LIGHTNING_ROD_URL = f"{PROXY_URL}/api/gateway/lightning-rod/chat/completions"

MODEL = "LightningRodLabs/foresight-v3"

MAX_RETRIES = 3
BASE_BACKOFF = 1.5

TOTAL_COST = 0.0


class AgentData(BaseModel):
    event_id: str
    title: str
    description: str
    cutoff: datetime
    metadata: dict


async def retry_with_backoff(func, max_retries: int = MAX_RETRIES):
    for attempt in range(max_retries):
        try:
            return await func()
        except httpx.TimeoutException as e:
            if attempt < max_retries - 1:
                delay = BASE_BACKOFF ** (attempt + 1)
                print(f"[RETRY] Timeout, retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                raise Exception(f"Max retries exceeded: {e}")
        except httpx.HTTPStatusError as e:
            try:
                error_detail = e.response.json().get("detail", str(e))
            except Exception:
                error_detail = e.response.text if hasattr(e.response, "text") else str(e)

            if e.response.status_code == 429:
                if attempt < max_retries - 1:
                    delay = BASE_BACKOFF ** (attempt + 1)
                    print(f"[RETRY] Rate limited (429), retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    raise Exception(f"Rate limit exceeded: {error_detail}")
            else:
                raise Exception(f"HTTP {e.response.status_code}: {error_detail}")
        except Exception:
            raise


def clip_probability(prediction: float) -> float:
    return max(0.0, min(1.0, prediction))


def parse_answer_tag(text: str) -> float | None:
    match = re.search(r"<answer>([\d.]+)</answer>", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


async def forecast_with_lightning_rod(event: AgentData) -> dict:
    global TOTAL_COST
    print(f"[FORECAST] Generating forecast with Lightning Rod ({MODEL})...")

    cutoff_date = event.cutoff.strftime("%Y-%m-%d %H:%M UTC")

    prompt = (
        f"Event: {event.title}\n\n"
        f"Description: {event.description}\n\n"
        f"Deadline: {cutoff_date}\n\n"
        "Will this event occur? Answer as a probability between 0 and 1 "
        "between <answer></answer> tags."
    )

    async def lightning_rod_call():
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "run_id": RUN_ID,
            }
            response = await client.post(LIGHTNING_ROD_URL, json=payload)
            response.raise_for_status()
            return response.json()

    try:
        result = await retry_with_backoff(lightning_rod_call)

        response_text = result["choices"][0]["message"]["content"]
        cost = result.get("cost", 0.0)
        TOTAL_COST += cost

        reasoning = result["choices"][0]["message"].get("reasoning", "")

        print(f"[FORECAST] Cost: ${cost:.6f} | Total: ${TOTAL_COST:.6f}")

        prediction = parse_answer_tag(response_text)
        if prediction is None:
            print("[FORECAST] Could not parse <answer> tag, defaulting to 0.5")
            prediction = 0.5

        prediction = clip_probability(prediction)
        print(f"[FORECAST] Prediction: {prediction}")

        return {
            "event_id": event.event_id,
            "prediction": prediction,
            "reasoning": reasoning or response_text,
        }

    except Exception as e:
        print(f"[FORECAST] Error: {e}")
        return {
            "event_id": event.event_id,
            "prediction": 0.5,
            "reasoning": "Unable to generate forecast. Returning neutral prediction.",
        }


async def run_agent(event: AgentData) -> dict:
    global TOTAL_COST
    TOTAL_COST = 0.0

    start_time = time.time()
    result = await forecast_with_lightning_rod(event)
    elapsed = time.time() - start_time

    print(f"[AGENT] Complete in {elapsed:.2f}s")
    print(f"[AGENT] Total run cost: ${TOTAL_COST:.6f}")

    return {
        "event_id": result["event_id"],
        "prediction": result["prediction"],
        "reasoning": result["reasoning"],
    }


def agent_main(event_data: dict) -> dict:
    event = AgentData.model_validate(event_data)
    print(f"\n[AGENT] Running forecast for event: {event.event_id}")
    print(f"[AGENT] Title: {event.title}")

    return asyncio.run(run_agent(event))
