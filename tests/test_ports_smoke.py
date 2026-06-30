from __future__ import annotations

from collections.abc import Sequence

import artemis
from artemis.ports import CapabilityStore, MemoryPort, ModelPort, Scheduler, TransportPort
from artemis.types import Message, ModelResponse, Usage


def test_package_imports() -> None:
    assert isinstance(artemis.__version__, str)


def test_ports_are_protocols_and_runtime_checkable() -> None:
    assert getattr(ModelPort, "_is_protocol") is True
    assert getattr(MemoryPort, "_is_protocol") is True
    assert getattr(TransportPort, "_is_protocol") is True
    assert getattr(CapabilityStore, "_is_protocol") is True
    assert getattr(Scheduler, "_is_protocol") is True

    assert getattr(ModelPort, "_is_runtime_protocol") is True
    assert getattr(MemoryPort, "_is_runtime_protocol") is True
    assert getattr(TransportPort, "_is_runtime_protocol") is True
    assert getattr(CapabilityStore, "_is_runtime_protocol") is True
    assert getattr(Scheduler, "_is_runtime_protocol") is True

    assert isinstance(object(), ModelPort) in {False, True}
    assert isinstance(object(), MemoryPort) in {False, True}
    assert isinstance(object(), TransportPort) in {False, True}
    assert isinstance(object(), CapabilityStore) in {False, True}
    assert isinstance(object(), Scheduler) in {False, True}


class StubModel:
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
            text="ok",
            model_id=model or "stub",
            structured=response_schema,
            finish_reason="stop",
            usage=Usage(prompt_tokens=len(messages), completion_tokens=1, total_tokens=2),
        )


def test_minimal_model_stub_satisfies_protocol() -> None:
    assert isinstance(StubModel(), ModelPort)
