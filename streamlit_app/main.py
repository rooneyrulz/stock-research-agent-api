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

from streamlit_app.service import get_analysis

st.set_page_config(page_title="Stock Research Agent API (dev)", page_icon="📈")

st.title("📈 Stock Research Agent API — wiring check")
st.caption("Bare-bones Step 1: raw JSON output, no UI polish yet.")

query = st.text_input(
    "Query",
    placeholder="e.g. should I buy TCS? / compare INFY and WIPRO / give me some momentum stocks / hi",
)

if st.button("Run", type="primary", disabled=not query.strip()):
    with st.spinner("Calling the backend..."):
        response = get_analysis(query)

    st.subheader("Result")
    st.json(response.model_dump(mode="json"))
