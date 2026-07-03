import json
from collections.abc import Sequence

import pytest

from artemis.data.read import DEFAULT_DOMAINS, ReadService
from artemis.data.store import DataStore, Record
from artemis.types import Message, ModelResponse, Usage


class FakePhraser:
    def __init__(
        self, *, answer: str = "You have Standup at 9am.", raises: Exception | None = None
    ) -> None:
        self._answer = answer
        self._raises = raises
        self.calls: list[list[Message]] = []
        self.models: list[str | None] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append(list(messages))
        self.models.append(model)
        if self._raises is not None:
            raise self._raises
        return ModelResponse(
            text=json.dumps({"answer": self._answer}),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _seed(store: DataStore, **over: object) -> None:
    base = dict(
        domain="calendar",
        kind="event",
        key="e1",
        payload={"secret_marker": "PAYLOAD_ONLY"},
        sanitized_text="Standup at 9am on 2026-08-22",
        source="today-calendar",
        fetched_at=100.0,
        owner_fields={},
    )
    base.update(over)
    store.upsert(Record(**base))  # type: ignore[arg-type]


def test_resolve_domain() -> None:
    svc = ReadService(DataStore(), phraser=FakePhraser())
    assert svc.resolve_domain("what's on my CALENDAR today").domain == "calendar"  # type: ignore[union-attr]
    assert svc.resolve_domain("any meetings tomorrow?").domain == "calendar"  # type: ignore[union-attr]
    assert svc.resolve_domain("what's the weather") is None


@pytest.mark.asyncio
async def test_read_no_domain_match_returns_none() -> None:
    svc = ReadService(DataStore(), phraser=FakePhraser())
    assert await svc.read("what's the weather in Tokyo") is None


@pytest.mark.asyncio
async def test_read_empty_store_returns_none() -> None:
    svc = ReadService(DataStore(), phraser=FakePhraser())
    assert await svc.read("what's on my calendar") is None  # domain matched but no rows


@pytest.mark.asyncio
async def test_read_phrases_from_rows() -> None:
    store = DataStore()
    _seed(store)
    phraser = FakePhraser(answer="You have Standup at 9am.")
    svc = ReadService(store, phraser=phraser)
    result = await svc.read("what's on my calendar")
    assert result is not None
    assert result.domain == "calendar"
    assert result.answer == "You have Standup at 9am."
    assert phraser.models == ["haiku"]


@pytest.mark.asyncio
async def test_phraser_sees_sanitized_text_not_payload() -> None:
    store = DataStore()
    _seed(store)  # payload has secret_marker=PAYLOAD_ONLY; sanitized_text does not
    phraser = FakePhraser()
    svc = ReadService(store, phraser=phraser)
    await svc.read("what's on my calendar")
    user_content = phraser.calls[0][1].content
    assert "Standup at 9am on 2026-08-22" in user_content  # sanitized_text is present
    assert "PAYLOAD_ONLY" not in user_content  # raw payload is NOT fed to the LLM


@pytest.mark.asyncio
async def test_phraser_failure_returns_none() -> None:
    store = DataStore()
    _seed(store)
    svc = ReadService(store, phraser=FakePhraser(raises=RuntimeError("down")))
    assert await svc.read("what's on my calendar") is None  # degrade to fall-through


def test_default_domains_include_calendar() -> None:
    assert any(d.domain == "calendar" for d in DEFAULT_DOMAINS)
