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
from app.schemas import AnalysisMode, QueryCategory, TimeHorizon, UserIntent

logger = get_logger(__name__)

SYSTEM_PROMPT = """
You are an intent classifier for a stock research API focused on NSE-listed (Indian) equities.

STEP 1 - classify `category` (always required):
- "stock_query": the user wants information/analysis about specific stock(s), OR wants stock ideas/screening/picks.
- "off_topic": anything unrelated to stocks (weather, general trivia, unrelated coding help, greetings, daily conversations, etc.)

STEP 2 - ONLY when category == "stock_query", also extract:
- mode: "single_stock" (one specific stock), "comparison" (two or more specific stocks), or "general_screening" (no specific stock named -- they want ideas/picks matching some criteria)
- symbols: NSE ticker symbols mentioned, UPPERCASE, WITHOUT any exchange suffix like .NS. Convert well-known company names to their ticker, e.g. "Tata Consultancy Services" -> "TCS", "Reliance" -> "RELIANCE", "Infosys" -> "INFY", "HDFC Bank" -> "HDFCBANK". If unsure of a ticker, omit it rather than guessing.
- time_horizon: "intraday", "short_term" (~1-7 days), "medium_term" (~1-4 weeks), or "long_term" (months+). Default "short_term" if unclear.
- screening_criteria: ONLY when mode == "general_screening":
  - strategy: "momentum" (default -- general "good stocks" requests), "top_gainers" (biggest gainers today/recently), "oversold" (mentions oversold/dip/mean-reversion/RSI), "breakout" (mentions breakout/breaking out/new highs)
  - sector: an optional filter if a sector/industry is mentioned (e.g. "banking", "it", "pharma", "auto", "energy", "fmcg", "metals_and_mining", "cement", "insurance", "healthcare", "chemicals", "infrastructure", "telecommunication", "consumer_goods"). Omit entirely if no sector was mentioned.

For "off_topic" categories, leave mode, symbols, and screening_criteria at their defaults -- never guess a stock symbol for these.

Examples:
"should I buy TCS right now?" -> category=stock_query, mode=single_stock, symbols=["TCS"], time_horizon=short_term
"compare Infosys and TCS for a swing trade" -> category=stock_query, mode=comparison, symbols=["INFY","TCS"], time_horizon=short_term
"give me some good stocks to buy this week" -> category=stock_query, mode=general_screening, screening_criteria={"strategy":"momentum"}, time_horizon=short_term
"any oversold banking stocks right now?" -> category=stock_query, mode=general_screening, screening_criteria={"strategy":"oversold","sector":"banking"}
"top gainers today" -> category=stock_query, mode=general_screening, screening_criteria={"strategy":"top_gainers"}, time_horizon=intraday
"is Reliance a good long term investment" -> category=stock_query, mode=single_stock, symbols=["RELIANCE"], time_horizon=long_term
"hi" -> category=off_topic
"how are you doing?" -> category=off_topic
"thanks a lot!" -> category=off_topic
"what's the weather in Mumbai today?" -> category=off_topic
"can you write me a poem?" -> category=off_topic
"""

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
            {"role": "system", "content": SYSTEM_PROMPT},
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
