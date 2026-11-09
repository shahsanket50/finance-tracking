"""Budget CRUD endpoints. Implements PRD §12 (Budget Management).

CRUD operates on the mutable `budgets` table (TRD §3.2).
Utilization (net spend) is a pure derivation in utilization.py; its API route is deferred
to Wave 6, when categorization decisions are persisted (B6, T5).
Hard DELETE on budgets is correct here: unlike accounts, no event-log row
references a budget ID, so deleting the row leaves the event log intact.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api_errors import BUDGET_DUPLICATE, DATABASE_INTEGRITY_ERROR, ApiError
from core.models.mutable import Budget
from db import get_db, is_unique_violation
from processing.budgets.schemas import BudgetCreate, BudgetResponse, BudgetUpdate

BUDGET_UNIQUE_CONSTRAINT = "uq_budgets_user_category_month"

router = APIRouter(prefix="/budgets", tags=["budgets"])

# TODO: replace with real auth dependency in Phase 5
_STUB_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _require_budget(db: Session, user_id: uuid.UUID, budget_id: uuid.UUID) -> Budget:
    budget = db.scalar(select(Budget).where(Budget.id == budget_id, Budget.user_id == user_id))
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return budget


@router.get("", response_model=list[BudgetResponse])
def list_budgets(db: Session = Depends(get_db)) -> list[BudgetResponse]:  # noqa: B008
    """List all budgets for the authenticated user."""
    budgets = db.scalars(select(Budget).where(Budget.user_id == _STUB_USER_ID)).all()
    return [BudgetResponse.from_orm_budget(b) for b in budgets]


@router.post("", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
def create_budget(body: BudgetCreate, db: Session = Depends(get_db)) -> BudgetResponse:  # noqa: B008
    """Create a budget. 409 only for the (user, category, month) unique key; any other
    integrity failure (e.g. a missing user) is a structured 500, never "duplicate"."""
    now = datetime.now(UTC)
    budget = Budget(
        id=uuid.uuid4(),
        user_id=_STUB_USER_ID,
        category=body.category,
        month=body.month,
        target_paise=body.target_paise,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():  # savepoint: a failed insert doesn't poison the session
            db.add(budget)
            db.flush()
    except IntegrityError as err:
        if is_unique_violation(err, BUDGET_UNIQUE_CONSTRAINT):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ApiError(
                    code=BUDGET_DUPLICATE,
                    message="A budget for this category and month already exists",
                ).model_dump(),
            ) from err
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ApiError(code=DATABASE_INTEGRITY_ERROR, message=str(err.orig)).model_dump(),
        ) from err
    db.commit()
    db.refresh(budget)
    return BudgetResponse.from_orm_budget(budget)


@router.get("/{budget_id}", response_model=BudgetResponse)
def get_budget(budget_id: uuid.UUID, db: Session = Depends(get_db)) -> BudgetResponse:  # noqa: B008
    """Get a single budget by ID."""
    budget = _require_budget(db, _STUB_USER_ID, budget_id)
    return BudgetResponse.from_orm_budget(budget)


@router.patch("/{budget_id}", response_model=BudgetResponse)
def patch_budget(
    budget_id: uuid.UUID,
    body: BudgetUpdate,
    db: Session = Depends(get_db),  # noqa: B008
) -> BudgetResponse:
    """Update target_paise on an existing budget. category and month are immutable."""
    budget = _require_budget(db, _STUB_USER_ID, budget_id)
    budget.target_paise = body.target_paise
    budget.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(budget)
    return BudgetResponse.from_orm_budget(budget)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: uuid.UUID, db: Session = Depends(get_db)) -> None:  # noqa: B008
    """Delete a budget row. Transaction data in the event log is never touched."""
    budget = _require_budget(db, _STUB_USER_ID, budget_id)
    db.delete(budget)
    db.commit()
