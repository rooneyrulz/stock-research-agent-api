"""
The ONLY seam between the Streamlit frontend and the backend.

Design decisions, and why:

1. In-process call, not HTTP. `run_analysis()` is imported and called
   directly rather than the frontend making an HTTP request to a running
   FastAPI server. This keeps the whole thing a single deployable unit on
   Streamlit Community Cloud (which only runs one process), and means
   nothing under app/ has to change or even be aware a frontend exists.

2. Secrets bridging. Locally, app/config.py's Settings() reads from a
   .env file. On Streamlit Cloud there is no .env -- secrets are provided
   via st.secrets instead. Rather than touch app/config.py to know about
   Streamlit (which would violate "don't change the API"), this module
   copies whatever's in st.secrets into os.environ *before* anything
   calls get_settings() for the first time. Settings() is only actually
   constructed lazily (see the @lru_cache on get_settings), so as long as
   this bridging runs at import time -- before any button click triggers
   real work -- both environments work unmodified.

3. A safety net around run_analysis(). The backend's own pipeline already
   catches essentially everything internally (that's the whole point of
   Phase 1/2's reliability work) and is not expected to raise. This
   try/except exists anyway as defense-in-depth so the Streamlit UI can
   make an absolute guarantee: it will never show a raw traceback page,
   regardless of what happens two layers down.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from app.logging_config import get_logger
from app.schemas import AnalysisResponse

logger = get_logger(__name__)


def _bridge_secrets_to_env() -> None:
    """Copy st.secrets into os.environ, without overriding anything
    already set (e.g. a local .env or an explicitly exported env var
    takes priority). Safe to call even when no secrets.toml exists at
    all -- Streamlit raises in that case, and we just skip silently."""
    try:
        import streamlit as st

        for key in st.secrets:
            value = st.secrets[key]
            if key in os.environ:
                continue
            if isinstance(value, (str, int, float, bool)):
                os.environ[key] = str(value)
    except Exception:  # noqa: BLE001
        # No secrets.toml (e.g. plain local run relying on .env), or
        # Streamlit's secrets machinery isn't available for some reason.
        # Either way, fall through and let app/config.py's own .env
        # loading (or already-exported env vars) handle it.
        return


# Run once, at import time -- before any Streamlit page code or button
# handler could trigger a call into the backend.
_bridge_secrets_to_env()


def _failure_response(query: str, error: Exception) -> AnalysisResponse:
    """Last-resort fallback if run_analysis() raises despite its own
    internal safety nets. Keeps the same fixed AnalysisResponse shape so
    every UI component downstream only ever has to handle one type."""
    logger.exception("frontend_service_unexpected_error", query=query)
    return AnalysisResponse(
        status="failed",
        request_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
        query=query,
        summary=(
            "Something went wrong while analyzing this request. This has been logged -- "
            "please try again in a moment."
        ),
        warnings=[f"{type(error).__name__}: {error}"],
    )


def get_analysis(query: str) -> AnalysisResponse:
    """The single function the Streamlit app calls. Never raises."""
    from app.pipeline import (
        run_analysis,  # imported lazily so secrets bridging above always runs first
    )

    query = query.strip()
    try:
        return run_analysis(query)
    except Exception as exc:  # noqa: BLE001
        return _failure_response(query, exc)