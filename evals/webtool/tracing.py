"""ModelPort tracing for web-tool eval runs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import time

from pydantic import BaseModel, ConfigDict

from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse


class TraceCall(BaseModel):
    """One traced model call."""

    model_config = ConfigDict(frozen=True)

    stage: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    cost_usd: float
    prompt_cache_key: str | None
    max_tokens: int | None
    response_text: str


class StageAggregate(BaseModel):
    """Aggregated model tracing for one stage."""

    model_config = ConfigDict(frozen=True)

    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float


@dataclass(frozen=True)
class TokenPrice:
    """Per-token price for cost accounting."""

    prompt_usd: float = 0.0
    completion_usd: float = 0.0


class TracingModelPort:
    """Wrap a ModelPort and record best-effort tokens, cost, latency, and cache keys."""

    def __init__(
        self,
        inner: ModelPort,
        *,
        stage: str,
        max_tokens_cap: int,
        prices: dict[str, TokenPrice] | None = None,
    ) -> None:
        self._inner = inner
        self._stage = stage
        self._max_tokens_cap = max_tokens_cap
        self._prices = prices or {}
        self.calls: list[TraceCall] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """Complete through the wrapped model and append one trace record."""
        forwarded_max_tokens = self._bounded_max_tokens(max_tokens)
        started = time.perf_counter()
        response = await self._inner.complete(
            messages=messages,
            model=model,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=forwarded_max_tokens,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        price = self._prices.get(response.model_id, TokenPrice())
        cost = (
            response.usage.prompt_tokens * price.prompt_usd
            + response.usage.completion_tokens * price.completion_usd
        )
        self.calls.append(
            TraceCall(
                stage=self._stage,
                model_id=response.model_id,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                latency_ms=latency_ms,
                cost_usd=cost,
                prompt_cache_key=_prompt_cache_key(messages),
                max_tokens=forwarded_max_tokens,
                response_text=response.text,
            )
        )
        return response

    def aggregate(self) -> StageAggregate:
        """Return aggregate tracing for this wrapper's stage."""
        return aggregate_calls(self.calls).get(
            self._stage,
            StageAggregate(
                calls=0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_usd=0.0,
                latency_ms=0.0,
            ),
        )

    def _bounded_max_tokens(self, requested: int | None) -> int:
        if requested is None:
            return self._max_tokens_cap
        return min(requested, self._max_tokens_cap)


def aggregate_calls(calls: Sequence[TraceCall]) -> dict[str, StageAggregate]:
    """Aggregate traced calls by stage."""
    grouped: dict[str, list[TraceCall]] = {}
    for call in calls:
        grouped.setdefault(call.stage, []).append(call)

    return {
        stage: StageAggregate(
            calls=len(items),
            prompt_tokens=sum(item.prompt_tokens for item in items),
            completion_tokens=sum(item.completion_tokens for item in items),
            total_tokens=sum(item.total_tokens for item in items),
            cost_usd=sum(item.cost_usd for item in items),
            latency_ms=sum(item.latency_ms for item in items),
        )
        for stage, items in grouped.items()
    }


def _prompt_cache_key(messages: Sequence[Message]) -> str | None:
    for message in messages:
        if message.role == "system":
            digest = hashlib.sha256(message.content.encode("utf-8")).hexdigest()
            return digest[:16]
    return None
