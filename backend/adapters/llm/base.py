"""Provider-agnostic LLM adapter interface. Implements TRD §4.2 (T8)."""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMResult(BaseModel, Generic[T]):  # noqa: UP046
    """Result from an LLM completion."""

    output: T
    confidence_bps: int  # basis points, 0–10000
    model_id: str
    prompt_version: str


@runtime_checkable
class LLMAdapter(Protocol[T]):
    """Swap any implementation without changing call sites."""

    async def complete(
        self, prompt: str, output_schema: type[T], prompt_version: str
    ) -> LLMResult[T]:
        """Complete a prompt with structured output.

        Args:
            prompt: The prompt string to send to the model.
            output_schema: Pydantic model defining the expected output structure.
            prompt_version: Version identifier for prompt reproducibility.

        Returns:
            LLMResult with the parsed output, confidence score, model ID, and prompt version.

        Raises:
            LLMValidationError: If the model response does not conform to output_schema.
        """
        ...


class LLMValidationError(Exception):
    """Raised when the model response does not conform to output_schema."""

    pass


class BelowConfidenceThreshold(Exception):
    """Raised when confidence_bps < the caller's threshold."""

    def __init__(self, confidence_bps: int, threshold: int) -> None:
        self.confidence_bps = confidence_bps
        self.threshold = threshold
        super().__init__(f"confidence {confidence_bps} bps < threshold {threshold} bps")
