"""
Every shape of data that crosses a boundary in this system (API in/out,
agent task in/out) is a Pydantic model. Nothing gets parsed out of free text
anywhere.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AnalysisMode(str, Enum):
    SINGLE_STOCK = "single_stock"
    COMPARISON = "comparison"
    GENERAL_SCREENING = "general_screening"  # not implemented until Phase 2


class TimeHorizon(str, Enum):
    INTRADAY = "intraday"
    SHORT_TERM = "short_term"  # ~1-7 days
    MEDIUM_TERM = "medium_term"  # ~1-4 weeks
    LONG_TERM = "long_term"  # months+


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Sentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


# ---------------------------------------------------------------------------
# Intent parsing (query -> structured request)
# ---------------------------------------------------------------------------


class UserIntent(BaseModel):
    """What the intent-parsing step extracts from a free-text user query."""

    mode: AnalysisMode
    symbols: list[str] = Field(
        default_factory=list,
        description="NSE ticker symbols mentioned or implied, WITHOUT the .NS suffix, e.g. ['TCS', 'INFY']",
    )
    time_horizon: TimeHorizon = TimeHorizon.SHORT_TERM
    original_query: str = ""


# ---------------------------------------------------------------------------
# Agent task outputs
# ---------------------------------------------------------------------------


class MarketData(BaseModel):
    symbol: str
    current_price: float
    previous_close: float
    change_pct: float
    volume: int
    rsi_14: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    trend: str = Field(
        description="Short human description, e.g. 'uptrend, above both moving averages'"
    )


class NewsSentiment(BaseModel):
    symbol: str
    sentiment: Sentiment
    headline_count: int
    headlines: list[str] = Field(default_factory=list, max_length=5)
    summary: str = Field(
        description="1-3 sentence summary of what the news means for this stock"
    )


class StockRecommendation(BaseModel):
    symbol: str
    action: Action
    confidence: Confidence
    target_price: float | None = None
    stop_loss: float | None = None
    risk_reward_ratio: str | None = None
    reasoning: str = Field(
        description="Plain-English justification citing the technical + news evidence"
    )


# ---------------------------------------------------------------------------
# API request/response
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)


class SymbolResult(BaseModel):
    """Everything gathered for one symbol, bundled together."""

    symbol: str
    market_data: MarketData | None = None
    news_sentiment: NewsSentiment | None = None
    recommendation: StockRecommendation | None = None
    error: str | None = None


class AnalysisResponse(BaseModel):
    """The one fixed shape returned by POST /analyze, always."""

    status: str = Field(
        description="'completed', 'partial', 'clarification_needed', or 'failed'"
    )
    request_id: str
    timestamp: datetime
    query: str

    needs_clarification: bool = False
    clarification_message: str | None = None

    results: list[SymbolResult] = Field(default_factory=list)
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)

    model_config = {"use_enum_values": True}
