"""ModelPort wrapper that records completion telemetry."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime

from artemis.config import Settings
from artemis.obs import get_logger
from artemis.obs.telemetry.cost import CostModel
from artemis.obs.telemetry.store import CallTrace, TelemetryStore
from artemis.ports import Message, ModelPort, ModelResponse, Vector


class TracingModelPort:
    """Trace model completions while preserving the wrapped ModelPort behavior."""

    def __init__(
        self,
        inner: ModelPort,
        store: TelemetryStore,
        cost: CostModel,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._inner = inner
        self._store = store
        self._cost = cost
        self._settings = settings
        self._clock = clock

    # satisfies artemis.ports.ModelPort
    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """Delegate completion and record token, latency, cost, and model id."""

        t0 = time.perf_counter()
        resp = await self._inner.complete(
            role=role,
            messages=messages,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        usage = getattr(resp, "usage", None)
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or 0) or (prompt + completion)
        safe_role = role[:64]
        if prompt == completion == total == 0:
            get_logger("obs.tracing").warning("empty_usage", extra={"role": safe_role})
        model_role = self._settings.roles.get(role)
        model_id = model_role.model_id if model_role is not None else None
        trace = CallTrace(
            role=safe_role,
            model_id=model_id,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            latency_ms=latency_ms,
            cost_micros=self._cost.cost_micros(role, total),
            trace_id=None,
            at=self._clock(),
        )
        try:
            self._store.record_call(trace)
        except Exception as exc:
            get_logger("obs.tracing").warning(
                "record_call_failed",
                extra={"role": safe_role, "error_type": type(exc).__name__},
            )
        return resp

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Delegate streaming unchanged; streaming tokens are not traced in v1."""

        return self._inner.complete_stream(role=role, messages=messages, temperature=temperature)

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        """Delegate embeddings unchanged; embedding costs are excluded in v1."""

        return await self._inner.embed(role, texts)
