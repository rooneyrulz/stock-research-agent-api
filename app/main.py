from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.logging_config import get_logger, setup_logging
from app.pipeline import run_analysis
from app.schemas import AnalysisResponse, AnalyzeRequest

setup_logging()
logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title="Stock Research Agent API",
    description="Role-specific multi-agent NSE stock analysis, built on CrewAI + Groq.",
    version="0.1.0",
)


@app.middleware("http")
async def add_request_logging(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


@app.post("/analyze", response_model=AnalysisResponse)
def analyze(payload: AnalyzeRequest) -> AnalysisResponse:
    try:
        return run_analysis(payload.query)
    except Exception as exc:
        logger.exception("unhandled_pipeline_error", query=payload.query)
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "query": payload.query,
                "error": "An unexpected error occurred while processing your request.",
                "detail": str(exc) if settings.environment == "development" else None,
            },
        )
