"""
Groq is OpenAI-API-compatible, so we point CrewAI's native OpenAI provider
at Groq's base_url instead of pulling in the (heavy, and here unnecessary)
LiteLLM fallback dependency.

IMPORTANT GOTCHA, documented so nobody re-discovers this the hard way:
CrewAI's `LLM(model="<prefix>/<name>")` parsing strips a recognized prefix
(like "openai/") from the model string before sending it to the API, on the
assumption the prefix is CrewAI's own provider routing syntax. Groq's own
model IDs happen to also contain a literal "openai/" (e.g.
"openai/gpt-oss-120b" is the actual model id Groq expects) which would get
incorrectly stripped down to "gpt-oss-120b" and fail with a 404.

The fix: pass `provider="openai"` EXPLICITLY as a kwarg. That takes a
different code path in CrewAI that does NOT partition/strip the model
string, so the full literal Groq model id is sent through untouched. Verified
against crewai==1.15.x -- re-check if you upgrade CrewAI and requests start
404-ing on the model name.
"""

from __future__ import annotations

from crewai import LLM

from app.config import get_settings


def get_tool_llm() -> LLM:
    """LLM for agents that call tools. Needs to be good at emitting
    well-formed tool calls -- this is the model choice that matters most
    for reliability."""
    settings = get_settings()
    return LLM(
        model=settings.groq_tool_model,
        provider="openai",
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )


def get_reasoning_llm() -> LLM:
    """Cheaper/faster model for reasoning-only steps (no tools attached).
    Used for the final recommendation synthesis to save rate-limit budget."""
    settings = get_settings()
    return LLM(
        model=settings.groq_reasoning_model,
        provider="openai",
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
