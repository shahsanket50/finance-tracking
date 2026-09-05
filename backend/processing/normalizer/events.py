"""Event payload for merchant normalization decisions. TRD §9.2."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MerchantNormalizedPayload(BaseModel, frozen=True):
    """Event payload recording a merchant normalization decision.

    All LLM-based decisions are recorded as events and never recomputed on replay.
    """

    transaction_hash: str
    raw_narration: str
    canonical_name: str
    method: Literal["rule", "llm"]
    confidence_bps: int
    rule_id: str | None  # which rule matched, if method == "rule"
    prompt_version: str | None  # prompt version, if method == "llm"
