"""
Step 1 of the frontend build: prove the in-process wiring to the backend
works end-to-end. No styling, no tables, no charts yet -- those come in
later steps. This intentionally just dumps the raw AnalysisResponse as
JSON so we can see exactly what the backend returns for various query
types before building any presentation layer on top of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit_app.components.results_table import render_results_table
from streamlit_app.service import get_analysis

st.set_page_config(page_title="NSE Stock Research Agent", page_icon="📈", layout="wide")

st.title("📈 NSE Stock Research Agent - Wiring Check")
st.caption("Structured table + per-status handling replaces the raw JSON dump from Step 1.")

query = st.text_input(
    "Query",
    placeholder="e.g. should I buy TCS? / compare INFY and WIPRO / give me some momentum stocks / hi",
)

if st.button("Run", type="primary", disabled=not query.strip()):
    with st.spinner("Calling the backend..."):
        response = get_analysis(query)

    if response.status == "off_topic":
        st.info(response.summary)

    elif response.status == "clarification_needed":
        st.warning(response.clarification_message or response.summary)

    elif response.status == "failed":
        st.error(response.summary)

    else:  # completed / partial
        if response.warnings:
            for warning in response.warnings:
                st.warning(warning)
        render_results_table(response)

    with st.expander("🛠️ View raw response (debug)"):
        st.json(response.model_dump(mode="json"))
