"""Quota-aware model router."""

from __future__ import annotations

from collections.abc import Sequence

from artemis.model.errors import AllBackendsExhaustedError, FailoverEligibleError, ProviderError
from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse


class QuotaAwareRouter:
    """Try backends in order (subscription-first); fail over on FailoverEligibleError."""

    def __init__(self, backends: Sequence[tuple[str, ModelPort]]) -> None:
        if not backends:
            raise ValueError("QuotaAwareRouter needs at least one backend")
        self._backends = list(backends)

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        failures: list[tuple[str, ProviderError]] = []
        for name, backend in self._backends:
            try:
                return await backend.complete(
                    messages=messages,
                    model=model,
                    response_schema=response_schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except FailoverEligibleError as exc:
                failures.append((name, exc))
                continue
        raise AllBackendsExhaustedError(failures)
