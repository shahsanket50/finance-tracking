"""FastAPI application entry point. Implements TRD §1 (API layer).

This is the scaffold for Phase 0. Only the /health endpoint is live.
All other routes are added in subsequent tasks.
"""

from fastapi import FastAPI

from ingestion.api.router import router as ingestion_router

app = FastAPI(title="Finance Tracker API", version="0.1.0")

app.include_router(ingestion_router, prefix="/api/v1/statements", tags=["statements"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
