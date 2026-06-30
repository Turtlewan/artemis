from __future__ import annotations

from collections.abc import Sequence

import pytest

from artemis.model.errors import AllBackendsExhaustedError, QuotaExhaustedError
from artemis.model.router import QuotaAwareRouter
from artemis.ports.model import ModelPort
from artemis.spine.spine import Spine
from artemis.types import Message, ModelResponse, Usage


class FakeBackend:
    def __init__(
        self, *, name: str, response: ModelResponse | None = None, fail: bool = False
    ) -> None:
        self.name = name
        self.response = response or _response(name)
        self.fail = fail
        self.calls = 0

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, model, response_schema, temperature, max_tokens
        self.calls += 1
        if self.fail:
            raise QuotaExhaustedError(self.name, "quota reached")
        return self.response


@pytest.mark.asyncio
async def test_router_falls_over_after_quota_error() -> None:
    first = FakeBackend(name="codex", fail=True)
    second_response = _response("claude")
    second = FakeBackend(name="claude", response=second_response)
    router = QuotaAwareRouter([("codex", first), ("claude", second)])

    result = await router.complete(messages=[Message(role="user", content="hi")])

    assert result == second_response
    assert first.calls == 1
    assert second.calls == 1


@pytest.mark.asyncio
async def test_router_short_circuits_on_first_success() -> None:
    first_response = _response("codex")
    first = FakeBackend(name="codex", response=first_response)
    second = FakeBackend(name="claude")
    router = QuotaAwareRouter([("codex", first), ("claude", second)])

    result = await router.complete(messages=[Message(role="user", content="hi")])

    assert result == first_response
    assert first.calls == 1
    assert second.calls == 0


@pytest.mark.asyncio
async def test_router_raises_all_exhausted_with_backend_names() -> None:
    first = FakeBackend(name="codex", fail=True)
    second = FakeBackend(name="claude", fail=True)
    router = QuotaAwareRouter([("codex", first), ("claude", second)])

    with pytest.raises(AllBackendsExhaustedError) as exc_info:
        await router.complete(messages=[Message(role="user", content="hi")])

    assert [name for name, _failure in exc_info.value.failures] == ["codex", "claude"]


def test_router_satisfies_model_port_and_spine_accepts_it() -> None:
    router = QuotaAwareRouter([("codex", FakeBackend(name="codex"))])

    assert isinstance(router, ModelPort)
    Spine(model=router)


def _response(model_id: str) -> ModelResponse:
    return ModelResponse(
        text="ok",
        model_id=model_id,
        structured=None,
        finish_reason="stop",
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )
