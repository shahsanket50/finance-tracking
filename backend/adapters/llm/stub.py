"""Deterministic stub LLM adapter for testing. Never calls a real API."""

from __future__ import annotations

import typing
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from adapters.llm.base import LLMAdapter, LLMResult


def _make_default_instance(schema: type[BaseModel]) -> BaseModel:
    """Construct a schema instance using sensible defaults for each field."""
    kwargs: dict[str, Any] = {}
    for field_name, field_info in schema.model_fields.items():
        annotation = field_info.annotation
        origin = get_origin(annotation)
        args = get_args(annotation)

        # Literal["a", "b", ...] — pick the first valid value
        if origin is typing.Literal:
            kwargs[field_name] = args[0]
        # Optional[X] or Union[X, None] — use None
        elif type(None) in args:
            kwargs[field_name] = None
        elif annotation is str:
            kwargs[field_name] = ""
        elif annotation is int:
            kwargs[field_name] = 0
        elif annotation is float:
            kwargs[field_name] = 0
        elif annotation is bool:
            kwargs[field_name] = False
        elif origin is list or annotation is list:
            kwargs[field_name] = []
        elif origin is dict or annotation is dict:
            kwargs[field_name] = {}
        else:
            kwargs[field_name] = None
    return schema(**kwargs)


class StubLLMAdapter:
    """Deterministic stub satisfying the LLMAdapter Protocol. No real API calls."""

    def __init__(self, confidence_bps: int = 8000) -> None:
        self._confidence_bps = confidence_bps

    async def complete(
        self,
        prompt: str,
        output_schema: type[BaseModel],
        prompt_version: str,
    ) -> LLMResult[BaseModel]:
        output = _make_default_instance(output_schema)
        return LLMResult(
            output=output,
            confidence_bps=self._confidence_bps,
            model_id="stub-v0",
            prompt_version=prompt_version,
        )


# Verify at import time that StubLLMAdapter satisfies the Protocol.
assert isinstance(StubLLMAdapter(), LLMAdapter)
