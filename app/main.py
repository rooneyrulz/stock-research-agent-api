from fastapi import FastAPI

from app.config import get_settings
from app.logging_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title="Stock Research Agent API",
    description="Role-specific multi-agent NSE stock analysis, built on CrewAI + Groq.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}
