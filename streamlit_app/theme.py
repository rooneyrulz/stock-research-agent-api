"""
Central color palette for the whole frontend. Import colors from here --
never hardcode a hex value in a component file.

This file starts intentionally minimal (just color constants, used for
table/chart semantics). It grows in a later step to also wire up
.streamlit/config.toml and any custom CSS injection for native widgets
(buttons, inputs, etc.).
"""

from __future__ import annotations

BRAND_ACCENT = "#0E9F6E"  # teal-green
STRUCTURAL_ACCENT = "#005571"  # deep teal-blue

ACTION_COLORS: dict[str, str] = {
    "BUY": "#16A34A",
    "SELL": "#DC2626",
    "HOLD": "#D97706",
}

SENTIMENT_COLORS: dict[str, str] = {
    "POSITIVE": "#16A34A",
    "NEGATIVE": "#DC2626",
    "NEUTRAL": "#6B7280",
    "MIXED": "#D97706",
}

NEUTRAL_TEXT = "#374151"
MUTED_TEXT = "#9CA3AF"
