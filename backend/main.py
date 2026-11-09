"""FastAPI application entry point. Implements TRD §1 (API layer).

This is the scaffold for Phase 0. Only the /health endpoint is live.
All other routes are added in subsequent tasks.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from ingestion.api.router import router as ingestion_router
from processing.accounts.crud_router import router as accounts_crud_router
from processing.accounts.router import router as accounts_router
from processing.audit.router import router as audit_router
from processing.budgets.router import router as budgets_router

app = FastAPI(title="Finance Tracker API", version="0.1.0")

app.include_router(ingestion_router, prefix="/api/v1/statements")
app.include_router(audit_router, prefix="/api/v1/audit")
app.include_router(accounts_router, prefix="/api/v1/accounts")
app.include_router(accounts_crud_router, prefix="/api/v1")  # router prefix: /accounts
app.include_router(budgets_router, prefix="/api/v1")  # router prefix: /budgets


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")
