"""Event payload for merchant normalization decisions. TRD §9.2."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MerchantNormalizedPayload(BaseModel, frozen=True):
    """Event payload recording a merchant normalization decision.

    All LLM-based decisions are recorded as events and never recomputed on replay.
    frozen=True prevents mutation via normal attribute assignment.
    """

    transaction_hash: str
    raw_narration: str
    canonical_name: str
    method: Literal["rule", "llm"]
    confidence_bps: int = Field(..., ge=0, le=10000)
    rule_id: str | None  # set when method == "rule"
    prompt_version: str | None  # set when method == "llm"
