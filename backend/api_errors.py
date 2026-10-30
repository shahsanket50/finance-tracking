"""Structured API error bodies. Implements TRD §1 (API layer) and CLAUDE.md §1 (fail loudly).

Derivations raise ValueError/TypeError when recorded data violates their contract (a
non-int amount, an anchor for the wrong account, a corrupted duplicate hash). Routes map
those to a structured error instead of a bare 500 traceback, so the client can say
"this balance cannot be computed" rather than show a number.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel


class ApiError(BaseModel):
    code: str
    message: str


class ApiErrorResponse(BaseModel):
    detail: ApiError


LEDGER_INTEGRITY_ERROR = "ledger_integrity_error"
BALANCE_NOT_SUPPORTED = "balance_not_supported_for_account_type"

# For route decorators: documents the 500 body in OpenAPI. 422 keeps FastAPI's default schema
# in the docs; routes may also return an ApiError body under 422 for unsupported requests.
DERIVATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ApiErrorResponse,
        "description": "Recorded ledger data violates a derivation contract; no number returned.",
    },
}


def ledger_integrity_error(err: ValueError | TypeError) -> HTTPException:
    """A derivation rejected recorded data: loud, structured, and never a partial number."""
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=ApiError(code=LEDGER_INTEGRITY_ERROR, message=str(err)).model_dump(),
    )
