"""
Pure data-shaping logic, deliberately kept free of any `streamlit` import.
This is what makes it unit-testable without a Streamlit runtime, and it's
also what export.py (CSV download, added in a later step) will reuse
directly instead of re-deriving the same rows from a styled DataFrame.
"""

from __future__ import annotations

import pandas as pd

from app.schemas import SymbolResult

# Column order doubles as the display order in the table -- change here,
# not in results_table.py.
COLUMNS = [
    "Symbol",
    "Status",
    "Action",
    "Confidence",
    "Price",
    "Change %",
    "RSI (14)",
    "Trend",
    "Sentiment",
    "Target",
    "Stop Loss",
    "Risk/Reward",
    "Error",
]


def _row_for_result(result: SymbolResult) -> dict:
    if result.error or not result.recommendation:
        return {
            "Symbol": result.symbol,
            "Status": "❌ Error",
            "Action": None,
            "Confidence": None,
            "Price": None,
            "Change %": None,
            "RSI (14)": None,
            "Trend": None,
            "Sentiment": None,
            "Target": None,
            "Stop Loss": None,
            "Risk/Reward": None,
            "Error": result.error or "Unknown error",
        }

    md = result.market_data
    news = result.news_sentiment
    rec = result.recommendation

    return {
        "Symbol": result.symbol,
        "Status": "✅ OK",
        "Action": rec.action,
        "Confidence": rec.confidence,
        "Price": md.current_price if md else None,
        "Change %": md.change_pct if md else None,
        "RSI (14)": md.rsi_14 if md else None,
        "Trend": md.trend if md else None,
        "Sentiment": news.sentiment if news else "N/A",
        "Target": rec.target_price,
        "Stop Loss": rec.stop_loss,
        "Risk/Reward": rec.risk_reward_ratio,
        "Error": None,
    }


def results_to_dataframe(results: list[SymbolResult]) -> pd.DataFrame:
    """Flatten a list of SymbolResult into one row per symbol. Safe to call
    with an empty list -- returns an empty (but correctly-columned)
    DataFrame rather than raising, so callers never need a special case."""
    if not results:
        return pd.DataFrame(columns=COLUMNS)
    rows = [_row_for_result(r) for r in results]
    return pd.DataFrame(rows, columns=COLUMNS)
