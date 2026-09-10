"""
Intent parsing is what makes the API "interpret user messages like a human"
instead of only handling one hardcoded query shape (the old system always
ran the same fixed prompt regardless of what was asked).

This is deliberately a single direct call to Groq via the official SDK --
NOT a CrewAI agent. It's a one-shot classification task with no tool calls
and no multi-step reasoning, so a full agent is unnecessary overhead. Using
Groq's native JSON-schema structured output means the response is
guaranteed-parseable JSON; we still validate it into our Pydantic model as a
second line of defense and treat any failure as "ask the user to clarify"
rather than guessing.
"""

from __future__ import annotations

import json

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging_config import get_logger
from app.prompts.intent import INTENT_SYSTEM_PROMPT
from app.schemas import AnalysisMode, QueryCategory, TimeHorizon, UserIntent

logger = get_logger(__name__)

_INTENT_JSON_SCHEMA = UserIntent.model_json_schema()
# original_query is filled in by us afterwards, don't ask the model for it.
_INTENT_JSON_SCHEMA.get("properties", {}).pop("original_query", None)
if "required" in _INTENT_JSON_SCHEMA:
    _INTENT_JSON_SCHEMA["required"] = [
        f for f in _INTENT_JSON_SCHEMA["required"] if f != "original_query"
    ]


class IntentParsingError(Exception):
    """Raised when the query genuinely can't be classified after retries."""


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
)
def _call_groq_for_intent(client: Groq, model: str, query: str) -> dict:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "user_intent",
                "description": "Structured intent extracted from a stock research query",
                "schema": _INTENT_JSON_SCHEMA,
            },
        },
        temperature=0.0,
        max_tokens=300,
    )
    return json.loads(response.choices[0].message.content)


def parse_intent(query: str) -> UserIntent:
    """Never raises for garden-variety bad input -- falls back to a
    general_screening/needs-clarification-shaped intent so the pipeline can
    decide how to respond, rather than crashing the request."""
    settings = get_settings()
    # NOTE: unlike app/agents/llm_config.py (which talks to Groq through
    # CrewAI's native OpenAI-compatible client and needs the full
    # ".../openai/v1" base URL), the official `groq` SDK used here already
    # appends "/openai/v1/chat/completions" to whatever base_url you give it.
    # Passing settings.groq_base_url (which includes "/openai/v1") here
    # double-appends the path and 404s. Let the SDK use its own default
    # (https://api.groq.com) instead.
    client = Groq(api_key=settings.groq_api_key)

    try:
        raw = _call_groq_for_intent(client, settings.groq_reasoning_model, query)
        raw["original_query"] = query
        intent = UserIntent(**raw)
        logger.info(
            "intent_parsed",
            query=query,
            category=intent.category,
            mode=intent.mode,
            symbols=intent.symbols,
        )
        return intent
    except Exception as exc:  # noqa: BLE001
        logger.warning("intent_parsing_failed", query=query, error=str(exc))
        # Safe fallback: treat as screening with no symbols. The pipeline
        # layer turns this into a clarification request rather than
        # guessing at a stock symbol.
        return UserIntent(
            category=QueryCategory.STOCK_QUERY,
            mode=AnalysisMode.GENERAL_SCREENING,
            symbols=[],
            time_horizon=TimeHorizon.SHORT_TERM,
            original_query=query,
        )
