"""
Central configuration for the Stock Research Agent API.

Everything that could plausibly change between environments (models, keys,
rate limits, timeouts) lives here so the rest of the codebase never reads
os.environ directly. That makes the reliability knobs (retries, rate limits,
timeouts) easy to find and tune in one place.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Groq ---
    groq_api_key: str = Field(..., description="GROQ_API_KEY from console.groq.com")
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1")

    # Model used by agents that call tools. openai/gpt-oss-120b has the most
    # reliable native tool-calling behavior of Groq's free/developer-tier models.
    groq_tool_model: str = Field(default="openai/gpt-oss-120b")

    # Model used for reasoning-only steps (no tools). Cheaper + faster, saves
    # tokens/rate-limit budget on the free tier.
    groq_reasoning_model: str = Field(default="openai/gpt-oss-20b")

    # Free-tier developer plan on Groq is roughly 1K RPM / 250K TPM for the
    # gpt-oss models as of writing. Keep agents comfortably under that so a
    # single user session can't blow the whole app's budget. Verify current
    # limits at https://console.groq.com/docs/rate-limits before raising this.
    groq_max_requests_per_minute: int = Field(default=20)

    llm_temperature: float = Field(default=0.2)
    llm_max_tokens: int = Field(default=1024)

    # --- App behavior ---
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    log_dir: str = Field(default="logs")

    max_symbols_per_request: int = Field(default=3, description="Cap on comparison mode to protect rate limits")
    market_data_period: str = Field(default="6mo", description="yfinance history window for indicators")

    # Retry/backoff tuning
    tool_max_retries: int = Field(default=3)
    tool_retry_min_seconds: float = Field(default=1.0)
    tool_retry_max_seconds: float = Field(default=8.0)

    task_max_retries: int = Field(default=2, description="CrewAI task-level retries on schema validation failure")


@lru_cache
def get_settings() -> Settings:
    return Settings()
