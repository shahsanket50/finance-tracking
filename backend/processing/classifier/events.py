"""Category classification event payloads. TRD §9.2."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from processing.classifier.categories import Category


class TransactionCategorizedPayload(BaseModel, frozen=True):
    """Payload for a system category assignment (rule or LLM).

    All LLM-based decisions are recorded as events and never recomputed on replay.
    frozen=True prevents mutation via normal attribute assignment.
    """

    transaction_hash: str
    category: Category
    method: Literal["rule", "llm"]
    confidence_bps: int = Field(..., ge=0, le=10000)
    rule_id: str | None  # set when method == "rule"
    prompt_version: str | None  # set when method == "llm"
    merchant_canonical: str  # canonical name from normalizer, used as input


class CategoryCorrectedPayload(BaseModel, frozen=True):
    """Payload for a user's manual category correction.

    This event takes precedence over any prior TransactionCategorizedPayload
    for the same transaction_hash on replay. The original classification is
    preserved in prior_category — never erased.

    frozen=True prevents mutation via normal attribute assignment.
    """

    transaction_hash: str
    category: Category  # the corrected category (user's choice)
    prior_category: Category  # what the system originally assigned
    merchant_canonical: str  # used to update the per-user rule
    corrected_by: str  # user_id
