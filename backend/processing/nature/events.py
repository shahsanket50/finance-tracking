"""Nature tagger event payloads. Implements PRD §5.1, TRD §8.3."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Nature = Literal["essential_fixed", "essential_variable", "discretionary", "luxury"]

ALL_NATURES: tuple[str, ...] = (
    "essential_fixed",
    "essential_variable",
    "discretionary",
    "luxury",
)


class NatureTaggedPayload(BaseModel, frozen=True):
    """DECISION — recorded as an event (TRD §9.2).

    Nature tags only exist on expense transactions (TRD §8.3 invariant).
    Caller must enforce transaction_type == "expense" before calling tag_nature().
    The tagger also enforces this guard internally and raises ValueError otherwise.
    """

    transaction_hash: str
    nature: Nature
    method: Literal["rule", "llm"]
    confidence_bps: int = Field(..., ge=0, le=10000)
    rule_id: str | None
    prompt_version: str | None
    category: str  # the category that was used to derive the nature tag


class NatureCorrectedPayload(BaseModel, frozen=True):
    """User override of a system-assigned nature tag. DECISION — recorded as event."""

    transaction_hash: str
    nature: Nature
    prior_nature: Nature
    corrected_by: str
