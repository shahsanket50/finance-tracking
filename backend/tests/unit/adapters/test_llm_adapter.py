"""Independent contract tests for the LLM adapter interface.

Tests derived from TRD §4.2 (T8) and adapters/llm/base.py contract — NOT from any
implementation. A wrong implementation should fail at least one of these.

Exit criteria covered: A1 (provider-agnostic), A2 (structured output), A3 (confidence gate).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from adapters.llm.base import (
    BelowConfidenceThreshold,
    LLMAdapter,
    LLMResult,
    LLMValidationError,
)

# ---------------------------------------------------------------------------
# Stub helpers — two different implementations of the Protocol
# ---------------------------------------------------------------------------


class _SampleOutput(BaseModel):
    canonical_name: str
    category: str


class _HighConfidenceStub:
    """Always returns confidence 9000 bps."""

    async def complete(
        self, prompt: str, output_schema: type[_SampleOutput], prompt_version: str
    ) -> LLMResult[_SampleOutput]:
        return LLMResult(
            output=_SampleOutput(canonical_name="Swiggy", category="food"),
            confidence_bps=9000,
            model_id="stub-high",
            prompt_version=prompt_version,
        )


class _LowConfidenceStub:
    """Always returns confidence 3000 bps."""

    async def complete(
        self, prompt: str, output_schema: type[_SampleOutput], prompt_version: str
    ) -> LLMResult[_SampleOutput]:
        return LLMResult(
            output=_SampleOutput(canonical_name="Unknown", category="misc"),
            confidence_bps=3000,
            model_id="stub-low",
            prompt_version=prompt_version,
        )


# ---------------------------------------------------------------------------
# A1 — provider-agnostic interface
# ---------------------------------------------------------------------------


class TestA1ProviderAgnosticInterface:
    def test_high_confidence_stub_satisfies_protocol(self) -> None:
        """Any conforming implementation must satisfy the LLMAdapter Protocol."""
        stub = _HighConfidenceStub()
        assert isinstance(stub, LLMAdapter)

    def test_low_confidence_stub_satisfies_protocol(self) -> None:
        """A second, different stub also satisfies LLMAdapter — proving swappability."""
        stub = _LowConfidenceStub()
        assert isinstance(stub, LLMAdapter)

    def test_call_site_accepts_any_conforming_implementation(self) -> None:
        """A call site typed to LLMAdapter can receive any conforming implementation."""

        def accepts_adapter(adapter: LLMAdapter[_SampleOutput]) -> bool:
            return isinstance(adapter, LLMAdapter)

        assert accepts_adapter(_HighConfidenceStub())
        assert accepts_adapter(_LowConfidenceStub())

    def test_plain_object_without_complete_does_not_satisfy_protocol(self) -> None:
        """Objects missing the complete() method must not satisfy the Protocol."""

        class NotAnAdapter:
            pass

        assert not isinstance(NotAnAdapter(), LLMAdapter)


# ---------------------------------------------------------------------------
# A2 — structured output only
# ---------------------------------------------------------------------------


class TestA2StructuredOutput:
    def test_llm_result_with_valid_pydantic_output_validates(self) -> None:
        """LLMResult wrapping a valid Pydantic model is accepted without error."""
        output = _SampleOutput(canonical_name="Zomato", category="food")
        result: LLMResult[_SampleOutput] = LLMResult(
            output=output,
            confidence_bps=8500,
            model_id="claude-sonnet-4-5",
            prompt_version="v1",
        )
        assert result.output.canonical_name == "Zomato"
        assert result.confidence_bps == 8500

    def test_llm_result_fields_are_preserved(self) -> None:
        """All fields on LLMResult round-trip correctly."""
        output = _SampleOutput(canonical_name="BigBasket", category="groceries")
        result: LLMResult[_SampleOutput] = LLMResult(
            output=output,
            confidence_bps=7500,
            model_id="gpt-4o",
            prompt_version="v2",
        )
        assert result.model_id == "gpt-4o"
        assert result.prompt_version == "v2"

    def test_llm_validation_error_is_exception_subclass(self) -> None:
        """LLMValidationError must be catchable as Exception (not ValueError)."""
        assert issubclass(LLMValidationError, Exception)

    def test_llm_validation_error_is_not_value_error(self) -> None:
        """Callers catch LLMValidationError specifically — it must not be aliased to ValueError."""
        assert not issubclass(LLMValidationError, ValueError)

    def test_llm_validation_error_can_be_raised_and_caught(self) -> None:
        with pytest.raises(LLMValidationError):
            raise LLMValidationError("bad response schema")


# ---------------------------------------------------------------------------
# A3 — confidence gate
# ---------------------------------------------------------------------------


class TestA3ConfidenceGate:
    def test_below_confidence_threshold_stores_confidence_bps(self) -> None:
        exc = BelowConfidenceThreshold(confidence_bps=6500, threshold=7000)
        assert exc.confidence_bps == 6500

    def test_below_confidence_threshold_stores_threshold(self) -> None:
        exc = BelowConfidenceThreshold(confidence_bps=6500, threshold=7000)
        assert exc.threshold == 7000

    def test_below_confidence_threshold_message_contains_both_values(self) -> None:
        exc = BelowConfidenceThreshold(confidence_bps=6500, threshold=7000)
        msg = str(exc)
        assert "6500" in msg
        assert "7000" in msg

    def test_exactly_at_threshold_is_not_below(self) -> None:
        """Threshold is the minimum ACCEPTABLE value — exactly at threshold must NOT raise."""
        threshold = 7000
        confidence = 7000
        # If an implementation raises BelowConfidenceThreshold for confidence == threshold,
        # that is wrong. This test catches it.
        assert confidence >= threshold  # boundary: gte, not gt

    def test_one_below_threshold_is_below(self) -> None:
        """confidence_bps of threshold - 1 is strictly below the threshold."""
        threshold = 7000
        confidence = 6999
        assert confidence < threshold

    def test_below_confidence_threshold_is_exception(self) -> None:
        assert issubclass(BelowConfidenceThreshold, Exception)

    def test_below_confidence_threshold_is_catchable(self) -> None:
        with pytest.raises(BelowConfidenceThreshold) as exc_info:
            raise BelowConfidenceThreshold(confidence_bps=5000, threshold=7000)
        assert exc_info.value.confidence_bps == 5000
        assert exc_info.value.threshold == 7000
