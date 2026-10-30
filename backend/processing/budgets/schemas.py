"""Pydantic request/response schemas for the budgets API. Implements PRD §12."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from processing.classifier.categories import ALL_CATEGORIES


class BudgetCreate(BaseModel):
    category: str
    month: date
    # Accept int or str from client; validated as positive int internally
    target_paise: int = Field(..., gt=0)

    @field_validator("category")
    @classmethod
    def category_must_be_valid(cls, v: str) -> str:
        if v not in ALL_CATEGORIES:
            raise ValueError(f"category must be one of {ALL_CATEGORIES}, got {v!r}")
        return v

    @field_validator("month")
    @classmethod
    def month_must_be_first_of_month(cls, v: date) -> date:
        if v.day != 1:
            raise ValueError(f"month must be the first day of a month, got {v}")
        return v


class BudgetUpdate(BaseModel):
    """PATCH body — only target_paise is mutable. category and month are immutable."""

    target_paise: int = Field(..., gt=0)
    model_config = {"extra": "forbid"}


class BudgetResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    category: str
    month: date
    # Serialized as string — CLAUDE.md §3.5 (JSON numbers → IEEE-754 corruption)
    target_paise: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_budget(cls, budget: object) -> BudgetResponse:
        from core.models.mutable import Budget as BudgetORM

        b: BudgetORM = budget  # type: ignore[assignment]
        return cls(
            id=b.id,
            user_id=b.user_id,
            category=b.category,
            month=b.month,
            target_paise=str(b.target_paise),
            created_at=b.created_at,
            updated_at=b.updated_at,
        )
