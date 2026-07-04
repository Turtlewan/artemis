"""Tests for per-role model metering."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from artemis.model.meter import MeteredPort, ModelMeter
from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse, Usage


class _CacheUsage(Usage):
    cache_read_tokens: int
    cache_creation_tokens: int


class _FakePort:
    def __init__(self, *, model_id: str = "sonnet", usage: Usage | None = None) -> None:
        self._model_id = model_id
        self._usage = usage or Usage(prompt_tokens=3, completion_tokens=5, total_tokens=8)

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            text="{}",
            model_id=self._model_id,
            structured=None,
            finish_reason="stop",
            usage=self._usage,
        )


class _FailPort:
    def __init__(self, exc: RuntimeError) -> None:
        self._exc = exc

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        raise self._exc


def test_usage_aggregates_by_role_in_order() -> None:
    meter = ModelMeter(":memory:")
    meter.record(
        "selector", "claude_code", "haiku", prompt_tokens=3, completion_tokens=5, latency_ms=10
    )
    meter.record(
        "selector", "claude_code", "haiku", prompt_tokens=3, completion_tokens=5, latency_ms=10
    )
    meter.record(
        "extractor", "claude_code", "haiku", prompt_tokens=7, completion_tokens=9, latency_ms=1
    )

    usage = meter.usage()

    assert [row.role for row in usage] == ["extractor", "selector"]
    selector = usage[1]
    extractor = usage[0]
    assert selector.calls == 2
    assert selector.prompt_tokens == 6
    assert selector.completion_tokens == 10
    assert extractor.calls == 1


def test_usage_averages_latency() -> None:
    meter = ModelMeter(":memory:")
    meter.record(
        "selector", "claude_code", "haiku", prompt_tokens=0, completion_tokens=0, latency_ms=10
    )
    meter.record(
        "selector", "claude_code", "haiku", prompt_tokens=0, completion_tokens=0, latency_ms=20
    )

    assert meter.usage()[0].avg_latency_ms == 15.0


@pytest.mark.asyncio
async def test_metered_port_records_served_model_and_binding_provider() -> None:
    meter = ModelMeter(":memory:")
    port = MeteredPort(_FakePort(model_id="sonnet"), meter=meter, role="synth", provider="router")

    await port.complete(messages=[Message(role="user", content="hi")])

    row = meter._conn.execute("SELECT role, provider, model, latency_ms FROM calls").fetchone()
    assert row[:3] == ("synth", "router", "sonnet")
    assert row[3] >= 0


@pytest.mark.asyncio
async def test_metered_port_record_failure_is_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    meter = ModelMeter(":memory:")

    def _raise(
        role: str,
        provider: str,
        model: str,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        raise RuntimeError("meter failed")

    monkeypatch.setattr(meter, "record", _raise)

    resp = await MeteredPort(
        _FakePort(model_id="haiku"), meter=meter, role="selector", provider="claude_code"
    ).complete(messages=[Message(role="user", content="hi")])

    assert resp.model_id == "haiku"


@pytest.mark.asyncio
async def test_metered_port_inner_failure_propagates() -> None:
    meter = ModelMeter(":memory:")
    exc = RuntimeError("model failed")
    port = MeteredPort(_FailPort(exc), meter=meter, role="selector", provider="claude_code")

    with pytest.raises(RuntimeError) as raised:
        await port.complete(messages=[Message(role="user", content="hi")])

    assert raised.value is exc


def test_meter_persists_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "m.db"
    meter = ModelMeter(str(path))
    meter.record(
        "selector", "claude_code", "haiku", prompt_tokens=1, completion_tokens=2, latency_ms=3
    )
    meter.close()

    reopened = ModelMeter(str(path))

    assert reopened.usage()[0].calls == 1


def test_empty_meter_usage_is_empty() -> None:
    assert ModelMeter(":memory:").usage() == []


def test_metered_port_satisfies_model_port() -> None:
    meter = ModelMeter(":memory:")
    _check: ModelPort = MeteredPort(
        _FakePort(), meter=meter, role="selector", provider="claude_code"
    )
    assert isinstance(_check, MeteredPort)


@pytest.mark.asyncio
async def test_cache_tokens_recorded_and_default_to_zero_without_fields() -> None:
    meter = ModelMeter(":memory:")
    cache_usage = _CacheUsage(
        prompt_tokens=3,
        completion_tokens=5,
        total_tokens=26,
        cache_read_tokens=7,
        cache_creation_tokens=11,
    )
    cache_port = MeteredPort(
        _FakePort(model_id="haiku", usage=cache_usage),
        meter=meter,
        role="selector",
        provider="claude_code",
    )

    await cache_port.complete(messages=[Message(role="user", content="hi")])
    await cache_port.complete(messages=[Message(role="user", content="hi")])

    usage = meter.usage()[0]
    assert usage.cache_read_tokens == 14
    assert usage.cache_creation_tokens == 22

    plain_meter = ModelMeter(":memory:")
    plain_port = MeteredPort(
        _FakePort(usage=Usage(prompt_tokens=3, completion_tokens=5, total_tokens=8)),
        meter=plain_meter,
        role="reader",
        provider="claude_code",
    )
    await plain_port.complete(messages=[Message(role="user", content="hi")])

    plain_usage = plain_meter.usage()[0]
    assert plain_usage.cache_read_tokens == 0
    assert plain_usage.cache_creation_tokens == 0
