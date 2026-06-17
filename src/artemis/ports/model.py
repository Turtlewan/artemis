"""ModelPort — OpenAI-compatible inference port.

ASYNC PORT RULE (ADR-015): complete, complete_stream, and embed are
network I/O and thus async. ``ModelResponse`` is a pydantic BaseModel
so it serialises cleanly through the dispatch seam.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from artemis.ports.types import Message, Usage, Vector


class ModelResponse(BaseModel):
    """Structured response from a model call.

    Attributes:
        text: The generated text.
        finish_reason: ``stop``, ``length``, or other.
        usage: Token counts.
        origin: ``local`` or ``cloud`` (egress provenance).
        model_id: The concrete model that served this call.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str
    finish_reason: str = "stop"
    usage: Usage = Usage(0, 0, 0)
    origin: str = "local"
    model_id: str = ""


@runtime_checkable
class ModelPort(Protocol):
    """OpenAI-compatible model inference port.

    No ``tools`` / ``tool_choice`` parameter — DR-a's toolless-quarantine
    guarantee depends on this. No ``stream`` bool — use ``complete_stream``
    for streaming.
    """

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """Non-streaming completion.

        When ``response_schema`` is set, the adapter passes it as
        ``response_format`` for constrained decoding.
        """
        ...

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Streaming completion — yields text deltas."""
        ...

    async def embed(
        self,
        role: str,
        texts: Sequence[str],
    ) -> list[Vector]:
        """Embed texts via the model server (async — network I/O)."""
        ...
