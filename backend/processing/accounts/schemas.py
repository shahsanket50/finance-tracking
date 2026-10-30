"""Pydantic request/response schemas for the accounts API. Implements PRD §13."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

AccountType = Literal["savings", "current", "credit_card", "investment"]

SyncStatus = Literal["pending", "healthy", "stale", "failed", "deactivated"]


class AccountCreate(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=128)
    account_type: AccountType
    last4: str | None = Field(default=None, min_length=4, max_length=4, pattern=r"^\d{4}$")
    account_ref: str = Field(..., min_length=1, max_length=128)


class AccountUpdate(BaseModel):
    # account_ref is intentionally absent — it is set once at creation and is immutable.
    # Editing it would silently sever every past transaction's link to this account.
    model_config = {"extra": "forbid"}

    nickname: str | None = Field(None, min_length=1, max_length=128)
    account_type: AccountType | None = None
    last4: str | None = Field(default=None, min_length=4, max_length=4, pattern=r"^\d{4}$")


class AccountResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    nickname: str | None
    account_type: str | None
    last4: str | None
    account_ref: str | None
    sync_status: str
    last_synced_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountBalanceResponse(BaseModel):
    account_ref: str
    account_type: str
    # The field for the other account class is always None. The field for this class is
    # None when no statement anchor exists (balance unknown, never 0; ADR-022).
    # Serialized as strings to prevent float corruption (CLAUDE.md §3.5)
    derived_balance_paise: str | None  # savings / current: signed net asset
    outstanding_liability_paise: str | None  # credit_card: owed; negative = credit balance
    anchor_period_end: date | None  # period_end of the anchoring statement; None = no anchor
