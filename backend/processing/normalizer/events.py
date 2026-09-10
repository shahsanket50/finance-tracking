"""Event payload for merchant normalization decisions. TRD §9.2."""

from __future__ import annotations

from typing import Literal

# Field order must stay stable — values are stored as a tuple in _values.
_FIELDS: tuple[str, ...] = (
    "transaction_hash",
    "raw_narration",
    "canonical_name",
    "method",
    "confidence_bps",
    "rule_id",
    "prompt_version",
)

_FIELD_INDEX: dict[str, int] = {f: i for i, f in enumerate(_FIELDS)}


def _make_property(idx: int) -> property:
    return property(lambda self: object.__getattribute__(self, "_values")[idx])


class MerchantNormalizedPayload:
    """Event payload recording a merchant normalization decision.

    All LLM-based decisions are recorded as events and never recomputed on replay.

    Frozen: mutation via any mechanism raises AttributeError (no __dict__, fields
    are read-only properties backed by a tuple slot). Satisfies TRD §9.2 immutability.
    """

    __slots__ = ("_values",)

    # Read-only properties — object.__setattr__ cannot bypass these because
    # there is no __dict__ and no writable slot named after any field.
    transaction_hash: str = _make_property(_FIELD_INDEX["transaction_hash"])  # type: ignore[assignment]
    raw_narration: str = _make_property(_FIELD_INDEX["raw_narration"])  # type: ignore[assignment]
    canonical_name: str = _make_property(_FIELD_INDEX["canonical_name"])  # type: ignore[assignment]
    method: Literal["rule", "llm"] = _make_property(_FIELD_INDEX["method"])  # type: ignore[assignment]
    confidence_bps: int = _make_property(_FIELD_INDEX["confidence_bps"])  # type: ignore[assignment]
    rule_id: str | None = _make_property(_FIELD_INDEX["rule_id"])  # type: ignore[assignment]
    prompt_version: str | None = _make_property(_FIELD_INDEX["prompt_version"])  # type: ignore[assignment]

    def __init__(
        self,
        *,
        transaction_hash: str,
        raw_narration: str,
        canonical_name: str,
        method: Literal["rule", "llm"],
        confidence_bps: int,
        rule_id: str | None,
        prompt_version: str | None,
    ) -> None:
        if method not in ("rule", "llm"):
            raise ValueError(f"method must be 'rule' or 'llm', got {method!r}")
        object.__setattr__(
            self,
            "_values",
            (
                transaction_hash,
                raw_narration,
                canonical_name,
                method,
                confidence_bps,
                rule_id,
                prompt_version,
            ),
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__!r} object is frozen")

    def __repr__(self) -> str:
        pairs = ", ".join(f"{f}={getattr(self, f)!r}" for f in _FIELDS)
        return f"MerchantNormalizedPayload({pairs})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MerchantNormalizedPayload):
            return False
        return bool(
            object.__getattribute__(self, "_values") == object.__getattribute__(other, "_values")
        )

    def __hash__(self) -> int:
        return hash(object.__getattribute__(self, "_values"))
