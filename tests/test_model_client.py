from __future__ import annotations

from collections.abc import Sequence

import pytest

from artemis.model.client import ModelClient, ModelOutputError
from artemis.model.codex_provider import RawProvider
from artemis.ports.model import ModelPort
from artemis.types import Message


class FakeProvider(RawProvider):
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or ['{"answer": "ok"}']
        self.calls: list[Sequence[Message]] = []

    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> str:
        del model, schema
        self.calls.append(messages)
        if len(self.calls) <= len(self.responses):
            return self.responses[len(self.calls) - 1]
        return self.responses[-1]


def test_model_client_satisfies_model_port() -> None:
    assert isinstance(ModelClient(FakeProvider()), ModelPort)


@pytest.mark.asyncio
async def test_schema_path_returns_structured_output() -> None:
    client = ModelClient(FakeProvider(['{"answer": "ok"}']))

    response = await client.complete(
        messages=[Message(role="user", content="Return an answer")],
        response_schema=_answer_schema(),
    )

    assert response.structured == {"answer": "ok"}
    assert response.text == '{"answer": "ok"}'


@pytest.mark.asyncio
async def test_client_reasks_after_bad_json_then_succeeds() -> None:
    provider = FakeProvider(["not json", '{"answer": "ok"}'])
    client = ModelClient(provider)

    response = await client.complete(
        messages=[Message(role="user", content="Return an answer")],
        response_schema=_answer_schema(),
    )

    assert response.structured == {"answer": "ok"}
    assert len(provider.calls) == 2
    assert provider.calls[1][-1].role == "user"
    assert "Return only valid JSON" in provider.calls[1][-1].content


@pytest.mark.asyncio
async def test_client_raises_after_max_reasks() -> None:
    provider = FakeProvider(["not json", "still not json"])
    client = ModelClient(provider, max_reasks=1)

    with pytest.raises(ModelOutputError):
        await client.complete(
            messages=[Message(role="user", content="Return an answer")],
            response_schema=_answer_schema(),
        )

    assert len(provider.calls) == 2


def _answer_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
