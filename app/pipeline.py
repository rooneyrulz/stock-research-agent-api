"""
This module is the deterministic backbone of the system. It decides *what
happens*; the agents only decide *content*. That split is the main reason
this should be far more reliable than a freely-routing supervisor agent.

Flow for every request:
1. Parse intent (structured, see app/intent.py).
2. If there's nothing to analyze (no symbols, or screening mode which isn't
   built yet in Phase 1), return a clarification response -- a real answer,
   not an error, and not a guess.
3. Otherwise run one crew per symbol (capped by max_symbols_per_request),
   catching failures per-symbol so one bad ticker doesn't take down a
   comparison request.
4. Assemble the fixed AnalysisResponse shape, with a templated (not
   LLM-generated) summary -- deterministic, free, and avoids a fourth LLM
   call's worth of rate-limit budget and failure surface for Phase 1.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.agents.crew_factory import build_stock_crew
from app.config import get_settings
from app.intent import parse_intent
from app.logging_config import (
    bind_request_context,
    clear_request_context,
    get_logger,
    get_trace_logger,
)
from app.schemas import (
    AnalysisMode,
    AnalysisResponse,
    MarketData,
    NewsSentiment,
    StockRecommendation,
    SymbolResult,
)

logger = get_logger(__name__)
trace_log = get_trace_logger()


def _run_crew_for_symbol(symbol: str, time_horizon: str) -> SymbolResult:
    bind_request_context(symbol=symbol)
    try:
        crew = build_stock_crew(symbol, time_horizon=time_horizon)
        crew.kickoff()

        tasks = crew.tasks
        print(f"Tasks for {symbol}: {[t for t in tasks]}")  # Debugging line

        market_data = tasks[0].output.pydantic if tasks[0].output else None
        news_sentiment = tasks[1].output.pydantic if tasks[1].output else None
        recommendation = tasks[2].output.pydantic if tasks[2].output else None

        logger.info(
            "symbol_analysis_completed", symbol=symbol, action=recommendation.action
        )
        return SymbolResult(
            symbol=symbol,
            market_data=market_data if isinstance(market_data, MarketData) else None,
            news_sentiment=news_sentiment
            if isinstance(news_sentiment, NewsSentiment)
            else None,
            recommendation=recommendation
            if isinstance(recommendation, StockRecommendation)
            else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("symbol_analysis_failed", symbol=symbol, error=str(exc))
        return SymbolResult(symbol=symbol, error=str(exc))


def _build_summary(results: list[SymbolResult]) -> str:
    lines = []
    for r in results:
        if r.error or not r.recommendation:
            lines.append(
                f"{r.symbol}: could not complete analysis ({r.error or 'unknown error'})."
            )
            continue
        rec = r.recommendation
        price_bit = ""
        if rec.target_price is not None:
            price_bit = f" Target: {rec.target_price}"
            if rec.stop_loss is not None:
                price_bit += f", Stop-loss: {rec.stop_loss}."
        lines.append(
            f"{r.symbol}: {rec.action} ({rec.confidence} confidence).{price_bit} {rec.reasoning}"
        )
    return "\n\n".join(lines) if lines else "No results were produced for this query."


def run_analysis(query: str) -> AnalysisResponse:
    settings = get_settings()
    request_id = str(uuid.uuid4())
    bind_request_context(request_id=request_id)
    logger.info("analysis_request_received", query=query)

    try:
        intent = parse_intent(query)

        if not intent.symbols:
            message = (
                (
                    "I couldn't find a specific stock symbol in your message. "
                    "Could you name the NSE-listed stock(s) you'd like analyzed, "
                    "e.g. 'should I buy TCS' or 'compare INFY and WIPRO'? "
                    "General market screening without a named stock isn't supported yet."
                )
                if intent.mode == AnalysisMode.GENERAL_SCREENING
                else (
                    "I understood you want a specific stock analysis, but couldn't identify "
                    "which stock. Could you name it explicitly?"
                )
            )
            return AnalysisResponse(
                status="clarification_needed",
                request_id=request_id,
                timestamp=datetime.now(UTC),
                query=query,
                needs_clarification=True,
                clarification_message=message,
                summary=message,
            )

        symbols = intent.symbols[: settings.max_symbols_per_request]
        warnings = []
        if len(intent.symbols) > settings.max_symbols_per_request:
            warnings.append(
                f"Only analyzing the first {settings.max_symbols_per_request} symbols "
                f"({', '.join(symbols)}) to stay within rate limits."
            )

        results = [
            _run_crew_for_symbol(sym, intent.time_horizon.value) for sym in symbols
        ]

        failed = [r for r in results if r.error]
        if failed:
            warnings.append(
                f"Analysis failed for: {', '.join(r.symbol for r in failed)}."
            )
        status = (
            "failed"
            if len(failed) == len(results)
            else ("partial" if failed else "completed")
        )

        response = AnalysisResponse(
            status=status,
            request_id=request_id,
            timestamp=datetime.now(UTC),
            query=query,
            results=results,
            summary=_build_summary(results),
            warnings=warnings,
        )
        logger.info("analysis_request_completed", status=status, symbols=symbols)
        return response

    finally:
        clear_request_context()
