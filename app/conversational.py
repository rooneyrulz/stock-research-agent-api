"""
This module will have only general knowledge question answering pipeline.
"""


from __future__ import annotations

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """
You are a helpful NSE stock market related AI assistant. you will answer user queries with only your trained knowladge.
Do not use any tools
Do not make up any data. I want you to be honest. 
If the user asks for something you don't know, say so.

Examples
"how are you doing" -> "I'm a AI assistant, I'm doing well"
"what is the weather like" -> "I can't answer that, I'm only trained on stock market data"
"""

@retry(reraise=True, stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
def _call_groq_for_answer(client: Groq, model: str, query: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        temperature=0.0,
        max_tokens=300,
    )
    return response.choices[0].message.content


def generate_off_topic_reply(query: str) -> str:
    """Honest, non-hallucinating reply for questions unrelated to stock
    research (weather, general knowledge, etc.). No tool call is ever
    attempted for these -- there is nothing here that could plausibly be
    satisfied by get_market_data or get_recent_news, so pretending
    otherwise would only produce a wrong answer with false confidence."""

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
        answer = _call_groq_for_answer(client, settings.groq_reasoning_model, query)
        logger.info("off_topic_answer", query=query, answer=answer)
        return answer
    except Exception as exc:  # noqa: BLE001
        logger.warning("off_topic_answer_failed", query=query, error=str(exc))
        return "I can't answer that, I'm only trained on stock market data"