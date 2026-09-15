"""
Renders the results table for a completed/partial AnalysisResponse.

Two deliberate UX choices:
1. Long-form text (recommendation reasoning, news headlines) is kept OUT
   of the table and shown in a per-symbol expander instead. A data table
   with a paragraph crammed into one cell is hard to scan either way --
   better to keep the table dense/comparable and put prose where it has
   room to breathe.
2. Semantic coloring (BUY/SELL/HOLD, sentiment) uses a small fixed color
   map here rather than reaching into theme.py -- that gets consolidated
   once theme.py exists (a later step). Kept as a local, easy-to-find
   constant for now rather than scattering raw hex codes through the
   render logic itself.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.schemas import AnalysisResponse
from streamlit_app.utils.formatting import results_to_dataframe

_ACTION_COLORS = {"BUY": "#DCFCE7", "SELL": "#FEE2E2", "HOLD": "#FEF3C7"}
_SENTIMENT_COLORS = {
    "POSITIVE": "#DCFCE7",
    "NEGATIVE": "#FEE2E2",
    "NEUTRAL": "#F3F4F6",
    "MIXED": "#FEF3C7",
}


def _highlight_action(value: object) -> str:
    color = _ACTION_COLORS.get(value, "")
    return f"background-color: {color}" if color else ""


def _highlight_sentiment(value: object) -> str:
    color = _SENTIMENT_COLORS.get(value, "")
    return f"background-color: {color}" if color else ""


def _render_screening_caption(response: AnalysisResponse) -> None:
    if not response.screening_meta:
        return
    meta = response.screening_meta
    sector_bit = f", sector: **{meta.sector_filter}**" if meta.sector_filter else ""
    st.caption(
        f"🔎 Screening — strategy: **{meta.strategy_used}**{sector_bit} · "
        f"scanned {meta.universe_scanned} candidates · showing top {meta.candidates_returned}"
    )


def _render_detail_expanders(response: AnalysisResponse) -> None:
    for result in response.results:
        if result.error or not result.recommendation:
            continue
        with st.expander(f"🔍 {result.symbol} — full analysis"):
            if result.news_sentiment:
                st.markdown(f"**News summary:** {result.news_sentiment.summary}")
                if result.news_sentiment.headlines:
                    st.markdown("**Headlines:**")
                    for headline in result.news_sentiment.headlines:
                        st.markdown(f"- {headline}")
            st.markdown(
                f"**Recommendation reasoning:** {result.recommendation.reasoning}"
            )


def render_results_table(response: AnalysisResponse) -> pd.DataFrame:
    """Renders the table (+ screening caption + per-symbol detail
    expanders) and returns the underlying DataFrame, so a later export
    step can reuse it for CSV download without recomputing anything."""
    df = results_to_dataframe(response.results)
    if df.empty:
        st.info("No results to display for this query.")
        return df

    _render_screening_caption(response)

    styled = df.style.map(_highlight_action, subset=["Action"]).map(
        _highlight_sentiment, subset=["Sentiment"]
    )

    st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        column_config={
            "Price": st.column_config.NumberColumn("Price (₹)", format="₹%.2f"),
            "Change %": st.column_config.NumberColumn("Change %", format="%.2f%%"),
            "RSI (14)": st.column_config.ProgressColumn(
                "RSI (14)", min_value=0, max_value=100, format="%.0f"
            ),
            "Target": st.column_config.NumberColumn("Target (₹)", format="₹%.2f"),
            "Stop Loss": st.column_config.NumberColumn("Stop Loss (₹)", format="₹%.2f"),
        },
    )

    _render_detail_expanders(response)
    return df
