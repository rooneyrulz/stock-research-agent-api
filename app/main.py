from fastapi import FastAPI

app = FastAPI(
    title="Stock Research Agent API",
    description="Role-specific multi-agent NSE stock analysis, built on CrewAI + Groq.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": "development"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info", reload=True)
