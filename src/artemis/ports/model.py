"""Model provider port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from artemis.types import Message, ModelResponse


@runtime_checkable
class ModelPort(Protocol):
    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """One completion across any provider. When response_schema is given, the impl
        down-converts it per backend (strict OpenAI/Codex vs lenient Ollama vs Anthropic
        tool input_schema), validates the result client-side, and re-asks on failure."""
        ...
