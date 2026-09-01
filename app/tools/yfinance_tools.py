"""
Data tools -- both built on yfinance, which is free and needs no API key.

Why yfinance for both price data AND news:
- `Ticker.history()` gives OHLCV we compute RSI/SMA/MACD from ourselves
  (no pandas-ta dependency -- that package has a history of breaking with
  newer pandas/numpy releases, which is exactly the kind of fragility we're
  trying to remove).
- `Ticker.news` gives recent headlines for the same symbol, for free, with
  no separate signup/API key. That means Phase 1 has exactly one external
  data dependency instead of three (price API + news API + scraper).

Both tools:
- normalize the symbol (append .NS for NSE if no exchange suffix given)
- retry transient failures with backoff (tenacity)
- NEVER raise a raw exception back to the agent -- they return a small
  JSON error payload instead, so a bad symbol or a flaky network call
  becomes something the agent (and our logs) can reason about instead of
  a stack trace the agent has no way to recover from.
"""

from __future__ import annotations

import json
from typing import Any, Type

import pandas as pd
import yfinance as yf
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.logging_config import get_trace_logger

trace_log = get_trace_logger()

NSE_SUFFIX = ".NS"


def normalize_symbol(symbol: str) -> str:
    """RELIANCE -> RELIANCE.NS, but leaves already-suffixed / non-NSE symbols alone."""
    symbol = symbol.strip().upper()
    if "." in symbol:
        return symbol
    return f"{symbol}{NSE_SUFFIX}"


def _retryable() -> Any:
    settings = get_settings()
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.tool_max_retries),
        wait=wait_exponential(
            multiplier=1,
            min=settings.tool_retry_min_seconds,
            max=settings.tool_retry_max_seconds,
        ),
        retry=retry_if_exception_type(Exception),
    )


def _compute_rsi(closes: pd.Series, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()

    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    # Edge cases the formula above doesn't handle on its own:
    #   - zero losses in the window (all gains) -> maximally overbought, RSI = 100
    #   - zero gains AND zero losses (perfectly flat prices) -> neutral, RSI = 50
    rsi = rsi.where(loss != 0, other=100.0)
    flat = (gain == 0) & (loss == 0)
    rsi = rsi.where(~flat, other=50.0)

    value = rsi.iloc[-1]
    return round(float(value), 2) if pd.notna(value) else None


def _compute_macd(closes: pd.Series) -> tuple[float | None, float | None]:
    if len(closes) < 35:
        return None, None
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_val = macd_line.iloc[-1]
    signal_val = signal_line.iloc[-1]
    return (
        round(float(macd_val), 2) if pd.notna(macd_val) else None,
        round(float(signal_val), 2) if pd.notna(signal_val) else None,
    )


def _describe_trend(price: float, sma_50: float | None, sma_200: float | None) -> str:
    if sma_50 is None or sma_200 is None:
        return "insufficient history to determine trend"
    if price > sma_50 > sma_200:
        return "uptrend: price above both 50 and 200-day moving averages"
    if price < sma_50 < sma_200:
        return "downtrend: price below both 50 and 200-day moving averages"
    return "mixed/sideways: price and moving averages not aligned"


@_retryable()
def fetch_market_data(symbol: str, period: str | None = None) -> dict:
    settings = get_settings()
    yf_symbol = normalize_symbol(symbol)
    period = period or settings.market_data_period

    ticker = yf.Ticker(yf_symbol)
    hist = ticker.history(period=period)

    if hist.empty or len(hist) < 2:
        raise ValueError(
            f"No price history returned for '{yf_symbol}'. Check the symbol is correct."
        )

    closes = hist["Close"]
    current_price = float(closes.iloc[-1])
    previous_close = float(closes.iloc[-2])
    change_pct = round(((current_price - previous_close) / previous_close) * 100, 2)
    volume = int(hist["Volume"].iloc[-1])

    sma_50 = (
        round(float(closes.rolling(50).mean().iloc[-1]), 2)
        if len(closes) >= 50
        else None
    )
    sma_200 = (
        round(float(closes.rolling(200).mean().iloc[-1]), 2)
        if len(closes) >= 200
        else None
    )
    rsi_14 = _compute_rsi(closes)
    macd, macd_signal = _compute_macd(closes)

    return {
        "symbol": symbol.upper().replace(NSE_SUFFIX, ""),
        "current_price": round(current_price, 2),
        "previous_close": round(previous_close, 2),
        "change_pct": change_pct,
        "volume": volume,
        "rsi_14": rsi_14,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "macd": macd,
        "macd_signal": macd_signal,
        "trend": _describe_trend(current_price, sma_50, sma_200),
    }


@_retryable()
def fetch_news(symbol: str, max_items: int = 5) -> dict:
    yf_symbol = normalize_symbol(symbol)
    ticker = yf.Ticker(yf_symbol)
    raw_news = ticker.news or []

    headlines = []
    for item in raw_news[:max_items]:
        content = item.get("content", item)
        title = content.get("title") or item.get("title")
        if title:
            headlines.append(title)

    return {
        "symbol": symbol.upper().replace(NSE_SUFFIX, ""),
        "headline_count": len(headlines),
        "headlines": headlines,
    }


# ---------------------------------------------------------------------------
# CrewAI tool wrappers
# ---------------------------------------------------------------------------


class SymbolInput(BaseModel):
    symbol: str = Field(
        ...,
        description="NSE stock ticker symbol without exchange suffix, e.g. 'TCS', 'RELIANCE', 'INFY'",
    )


class MarketDataTool(BaseTool):
    name: str = "get_market_data"
    description: str = (
        "Fetch the current price, volume, and technical indicators "
        "(RSI-14, 50/200-day SMA, MACD) for one NSE-listed stock symbol. "
        "Call this exactly once per symbol you are asked to analyze."
    )
    args_schema: Type[BaseModel] = SymbolInput

    def _run(self, symbol: str) -> str:
        try:
            data = fetch_market_data(symbol)
            trace_log.info("tool_call_success", tool=self.name, symbol=symbol)
            return json.dumps(data)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see module docstring
            trace_log.warning(
                "tool_call_failed", tool=self.name, symbol=symbol, error=str(exc)
            )
            return json.dumps({"error": True, "symbol": symbol, "message": str(exc)})


class NewsTool(BaseTool):
    name: str = "get_recent_news"
    description: str = (
        "Fetch recent news headlines for one NSE-listed stock symbol. "
        "Call this exactly once per symbol. You must interpret the sentiment "
        "of the headlines yourself -- this tool only returns raw headlines."
    )
    args_schema: Type[BaseModel] = SymbolInput

    def _run(self, symbol: str) -> str:
        try:
            data = fetch_news(symbol)
            trace_log.info("tool_call_success", tool=self.name, symbol=symbol)
            return json.dumps(data)
        except Exception as exc:  # noqa: BLE001
            trace_log.warning(
                "tool_call_failed", tool=self.name, symbol=symbol, error=str(exc)
            )
            return json.dumps({"error": True, "symbol": symbol, "message": str(exc)})
