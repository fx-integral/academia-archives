import asyncio
import json
import os
import time
from datetime import datetime

import httpx
from pydantic import BaseModel

RUN_ID = os.getenv("RUN_ID")
if not RUN_ID:
    raise ValueError("RUN_ID environment variable is required but not set")

PROXY_URL = os.getenv("SANDBOX_PROXY_URL", "http://sandbox_proxy")
OPENAI_URL = f"{PROXY_URL}/api/gateway/openai"
LUNAR_CRUSH_URL = f"{PROXY_URL}/api/gateway/lunar-crush"

OPENAI_MODELS = ["gpt-5.2", "gpt-5", "gpt-5-mini"]
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
                    print(f"[RETRY] Rate limited, retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    raise Exception(f"Rate limit exceeded: {error_detail}")
            else:
                raise Exception(f"HTTP {e.response.status_code}: {error_detail}")
        except Exception:
            raise


def clip_probability(p: float) -> float:
    return max(0.0, min(1.0, p))


# -- Step 1: Extract topics via cheap LLM --


async def extract_topics(event: AgentData) -> list[str]:
    global TOTAL_COST

    openai_input = [
        {
            "role": "developer",
            "content": (
                "You extract search topics for a social media intelligence platform called LunarCrush. "
                "Given an event, return 2-3 short, specific topic keywords that would yield relevant "
                "social sentiment data. Topics should be lowercase, 1-3 words max. "
                "Examples: 'bitcoin', 'iran', 'oil prices', 'fed interest rates', 'nvidia earnings'.\n\n"
                "Return ONLY a JSON array of strings, nothing else."
            ),
        },
        {
            "role": "user",
            "content": f"Event: {event.title}\nDescription: {event.description}",
        },
    ]

    payload = {
        "model": "gpt-5-nano",
        "input": openai_input,
        "run_id": RUN_ID,
    }

    try:

        async def call():
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{OPENAI_URL}/responses", json=payload)
                r.raise_for_status()
                return r.json()

        data = await retry_with_backoff(call)
        cost = data.get("cost", 0.0)
        TOTAL_COST += cost

        text = _extract_openai_text(data).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        topics = json.loads(text)
        if isinstance(topics, list):
            result = [t.lower().strip() for t in topics if isinstance(t, str)]
            print(f"[TOPICS] Extracted: {result} (cost=${cost:.6f})")
            return result[:3]
    except Exception as e:
        print(f"[TOPICS] Extraction failed: {e}")

    return event.metadata.get("topics", [])[:2]


# -- Step 2: LunarCrush social data --


async def lc_whatsup(topic: str) -> dict | None:
    try:

        async def call():
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{LUNAR_CRUSH_URL}/whatsup", json={"topic": topic, "run_id": RUN_ID}
                )
                r.raise_for_status()
                return r.json()

        return await retry_with_backoff(call)
    except Exception as e:
        print(f"[LUNAR_CRUSH] whatsup '{topic}' failed: {e}")
        return None


async def lc_topic(topic: str) -> dict | None:
    try:

        async def call():
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{LUNAR_CRUSH_URL}/topic", json={"topic": topic, "run_id": RUN_ID}
                )
                r.raise_for_status()
                return r.json()

        return await retry_with_backoff(call)
    except Exception as e:
        print(f"[LUNAR_CRUSH] topic '{topic}' failed: {e}")
        return None


async def fetch_social_context(topics: list[str]) -> str:
    parts = []

    for topic in topics:
        print(f"[LUNAR_CRUSH] Fetching '{topic}'...")
        whatsup, topic_data = await asyncio.gather(lc_whatsup(topic), lc_topic(topic))

        if not whatsup and not topic_data:
            continue

        section = [f"\n### Social data for '{topic}'"]

        if whatsup:
            section.append(f"AI Summary: {whatsup.get('summary', 'N/A')}")
            for t in whatsup.get("supportive", []):
                section.append(f"  Bullish: {t['title']} ({t['percent']}%)")
            for t in whatsup.get("critical", []):
                section.append(f"  Bearish: {t['title']} ({t['percent']}%)")
            print(f"[LUNAR_CRUSH] '{topic}' whatsup OK")

        if topic_data:
            data = topic_data.get("data", {})
            section.append(
                f"Stats: rank={data.get('topic_rank', 'N/A')}, "
                f"trend={data.get('trend', 'N/A')}, "
                f"24h_interactions={data.get('interactions_24h', 'N/A')}"
            )
            print(f"[LUNAR_CRUSH] '{topic}' topic OK")

        parts.extend(section)

    if not parts:
        return ""
    return "\n## Social Intelligence (LunarCrush)\n" + "\n".join(parts)


# -- Step 3: OpenAI forecast with web search --


def _extract_openai_text(response_data: dict) -> str:
    for item in response_data.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("text"):
                return content["text"]
    return ""


def parse_prediction(text: str) -> tuple[float, str]:
    prediction = 0.5
    reasoning = ""
    for line in text.strip().split("\n"):
        if line.startswith("PREDICTION:"):
            try:
                prediction = clip_probability(float(line.replace("PREDICTION:", "").strip()))
            except ValueError:
                pass
        elif line.startswith("REASONING:"):
            reasoning = line.replace("REASONING:", "").strip()
    return prediction, reasoning


async def forecast(event: AgentData, social_context: str) -> dict:
    global TOTAL_COST
    cutoff_str = event.cutoff.strftime("%Y-%m-%d %H:%M UTC")

    messages = [
        {
            "role": "developer",
            "content": (
                "You are an expert forecaster. Estimate the probability of binary events (YES/NO).\n"
                "You have access to web search. Research current information before forecasting.\n"
                "Consider base rates, recent developments, expert opinions, and uncertainty.\n"
                "Use the full range 0.0 to 1.0. Avoid extremes unless evidence is overwhelming."
            ),
        },
        {
            "role": "user",
            "content": f"""**Event:** {event.title}

            **Description:** {event.description}

            **Deadline:** {cutoff_str}
            {social_context}

            Research this event using web search, then estimate the probability it resolves YES.

            **Output format (exactly):**
            PREDICTION: [number 0.0-1.0]
            REASONING: [2-4 sentences with key factors and uncertainties]""",
        },
    ]

    for i, model in enumerate(OPENAI_MODELS):
        print(f"[OPENAI] Trying {model} ({i+1}/{len(OPENAI_MODELS)})...")
        try:

            async def llm_call():
                async with httpx.AsyncClient(timeout=120.0) as client:
                    r = await client.post(
                        f"{OPENAI_URL}/responses",
                        json={
                            "model": model,
                            "input": messages,
                            "tools": [{"type": "web_search"}],
                            "run_id": RUN_ID,
                        },
                    )
                    r.raise_for_status()
                    return r.json()

            data = await retry_with_backoff(llm_call)
            cost = data.get("cost", 0.0)
            TOTAL_COST += cost
            text = _extract_openai_text(data)
            prediction, reasoning = parse_prediction(text)
            print(f"[OPENAI] prediction={prediction:.4f}, cost=${cost:.6f}")
            if reasoning:
                print(f"[OPENAI] {reasoning[:200]}")
            return {"event_id": event.event_id, "prediction": prediction}
        except Exception as e:
            print(f"[OPENAI] {model} failed: {e}")

    print("[OPENAI] All models failed, returning 0.5")
    return {"event_id": event.event_id, "prediction": 0.5}


# -- Agent --


async def run_agent(event: AgentData) -> dict:
    global TOTAL_COST
    TOTAL_COST = 0.0
    start_time = time.time()

    topics = await extract_topics(event)
    social_context = await fetch_social_context(topics) if topics else ""

    if social_context:
        print(f"[AGENT] Social context: {len(social_context)} chars")

    result = await forecast(event, social_context)

    elapsed = time.time() - start_time
    print(f"[AGENT] Done in {elapsed:.2f}s, total cost=${TOTAL_COST:.6f}")
    return result


def agent_main(event_data: dict) -> dict:
    event = AgentData.model_validate(event_data)
    print(f"\n[AGENT] Forecasting: {event.event_id}")
    print(f"[AGENT] Title: {event.title}")
    return asyncio.run(run_agent(event))
