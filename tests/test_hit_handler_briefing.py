from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Literal

import pytest

from artemis.manifest import ModuleManifest
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Vector
from artemis.proactive.briefing import briefing_manifest, build_briefing_check
from artemis.proactive.hit_handler import HitHandler, OutboundMessage, TemplateRegistry
from artemis.proactive.hook_types import Hit, HookResult, TickResult
from artemis.registry import ToolRegistry


class FakeModelPort:
    def __init__(self, lines: Sequence[str] | None = None, *, raises: bool = False) -> None:
        self.lines = list(lines) if lines is not None else None
        self.raises = raises
        self.calls = 0
        self.seen_messages: list[Sequence[Message]] = []

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls += 1
        self.seen_messages.append(messages)
        if self.raises:
            raise RuntimeError("model unavailable")
        lines = (
            self.lines
            if self.lines is not None
            else [
                f"llm line {index}"
                for index, line in enumerate(messages[1].content.splitlines(), 1)
                if line.strip()
            ]
        )
        return ModelResponse(text="\n".join(lines))

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        async def stream() -> AsyncIterator[str]:
            if False:
                yield ""

        return stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[0.0] for _ in texts]


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 1

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0] for _ in texts]

    async def embed_query(self, text: str) -> Vector:
        return [1.0]


class DeliverSpy:
    def __init__(self) -> None:
        self.calls: list[list[OutboundMessage]] = []

    def __call__(self, messages: list[OutboundMessage]) -> int:
        self.calls.append(messages)
        return len(messages)


def _hit(
    module: str,
    hook_name: str,
    *,
    needs_llm: bool,
    urgency: str = "normal",
    tier: int = 0,
    payload: dict[str, object] | None = None,
    dedup_value: str | None = None,
) -> Hit:
    return Hit(
        module=module,
        hook_name=hook_name,
        tier=0 if tier == 0 else 1,
        urgency=_urgency(urgency),
        needs_llm=needs_llm,
        dedup_key=f"{module}:{hook_name}",
        result=HookResult.of(payload or {"item": module}, dedup_value=dedup_value),
        delivery=None,
    )


def _tick(*hits: Hit) -> TickResult:
    return TickResult(tuple(hits), "hits", ())


def _templates() -> TemplateRegistry:
    templates = TemplateRegistry()
    templates.register_template(
        "calendar.reminder",
        lambda result: f"calendar template {result.payload['item']}",
    )
    templates.register_template(
        "tasks.due",
        lambda result: f"tasks template {result.payload['item']}",
    )
    templates.register_template(
        "mail.summary",
        lambda result: f"mail template {result.payload['item']}",
    )
    templates.register_template(
        "briefing.daily_briefing",
        lambda result: f"briefing template {sorted(result.payload)}",
    )
    return templates


def _urgency(value: str) -> Literal["low", "normal", "high"]:
    if value not in {"low", "normal", "high"}:
        raise ValueError(value)
    if value == "low":
        return "low"
    if value == "high":
        return "high"
    return "normal"


@pytest.mark.asyncio
async def test_template_path_makes_no_model_call() -> None:
    model = FakeModelPort()
    deliver = DeliverSpy()
    handler = HitHandler(model, _templates(), deliver)

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=False, payload={"item": "standup"}),
            _hit("tasks", "due", needs_llm=False, payload={"item": "report"}),
        )
    )

    assert model.calls == 0
    assert [message.body for message in messages] == [
        "calendar template standup",
        "tasks template report",
    ]
    assert deliver.calls == [messages]


@pytest.mark.asyncio
async def test_needs_llm_hits_use_one_batched_call_in_order() -> None:
    model = FakeModelPort(["first", "second", "third"])
    handler = HitHandler(model, _templates(), DeliverSpy())

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=True),
            _hit("tasks", "due", needs_llm=True),
            _hit("mail", "summary", needs_llm=True),
        )
    )

    assert model.calls == 1
    assert [message.body for message in messages] == ["first", "second", "third"]
    assert "<<<" in model.seen_messages[0][1].content


@pytest.mark.asyncio
async def test_mixed_tick_uses_templates_and_one_llm_call() -> None:
    model = FakeModelPort(["llm calendar", "llm mail"])
    handler = HitHandler(model, _templates(), DeliverSpy())

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=False, payload={"item": "template"}),
            _hit("calendar", "reminder", needs_llm=True),
            _hit("tasks", "due", needs_llm=False, payload={"item": "template"}),
            _hit("mail", "summary", needs_llm=True),
        )
    )

    assert model.calls == 1
    assert len(messages) == 4
    assert [message.body for message in messages] == [
        "calendar template template",
        "tasks template template",
        "llm calendar",
        "llm mail",
    ]


@pytest.mark.asyncio
async def test_urgency_maps_to_dispositions_and_low_digest() -> None:
    handler = HitHandler(FakeModelPort(), _templates(), DeliverSpy())

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=False, urgency="high"),
            _hit("tasks", "due", needs_llm=False, urgency="normal"),
            _hit("mail", "summary", needs_llm=False, urgency="low"),
        )
    )

    assert [(message.source, message.disposition) for message in messages] == [
        ("calendar.reminder", "immediate"),
        ("tasks.due", "deferrable"),
        ("digest", "digest"),
    ]


@pytest.mark.asyncio
async def test_batch_low_urgency_folds_into_one_digest_with_max_tier() -> None:
    handler = HitHandler(FakeModelPort(), _templates(), DeliverSpy())

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=False, urgency="low", tier=0),
            _hit("tasks", "due", needs_llm=False, urgency="low", tier=1),
            _hit("mail", "summary", needs_llm=False, urgency="low", tier=0),
        )
    )

    assert len(messages) == 1
    digest = messages[0]
    assert digest.source == "digest"
    assert digest.disposition == "digest"
    assert digest.tier == 1
    assert "calendar template calendar" in digest.body
    assert "tasks template tasks" in digest.body
    assert "mail template mail" in digest.body


@pytest.mark.asyncio
async def test_digest_filters_already_sent_per_hit() -> None:
    def already_sent(key: str | None, value: str | None) -> bool:
        return value in {"sent-a", "sent-b"}

    handler = HitHandler(
        FakeModelPort(),
        _templates(),
        DeliverSpy(),
        already_sent=already_sent,
    )

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=False, urgency="low", dedup_value="sent-a"),
            _hit("tasks", "due", needs_llm=False, urgency="low", dedup_value="unsent"),
            _hit("mail", "summary", needs_llm=False, urgency="low", dedup_value="sent-b"),
        )
    )

    assert len(messages) == 1
    assert "tasks template tasks" in messages[0].body
    assert "calendar template calendar" not in messages[0].body
    assert "mail template mail" not in messages[0].body


@pytest.mark.asyncio
async def test_digest_is_omitted_when_all_low_hits_already_sent() -> None:
    handler = HitHandler(
        FakeModelPort(),
        _templates(),
        DeliverSpy(),
        already_sent=lambda _key, _value: True,
    )

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=False, urgency="low"),
            _hit("tasks", "due", needs_llm=False, urgency="low"),
            _hit("mail", "summary", needs_llm=False, urgency="low"),
        )
    )

    assert messages == []


@pytest.mark.asyncio
async def test_model_failure_degrades_to_template_renders() -> None:
    model = FakeModelPort(raises=True)
    handler = HitHandler(model, _templates(), DeliverSpy())

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=True, payload={"item": "fallback"}),
            _hit("tasks", "due", needs_llm=True, payload={"item": "fallback"}),
        )
    )

    assert model.calls == 1
    assert [message.body for message in messages] == [
        "calendar template fallback",
        "tasks template fallback",
    ]


@pytest.mark.asyncio
async def test_partial_llm_line_mismatch_falls_back_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = FakeModelPort(["only first"])
    handler = HitHandler(model, _templates(), DeliverSpy())

    messages = await handler.handle(
        _tick(
            _hit("calendar", "reminder", needs_llm=True, payload={"item": "a"}),
            _hit("tasks", "due", needs_llm=True, payload={"item": "b"}),
            _hit("mail", "summary", needs_llm=True, payload={"item": "c"}),
        )
    )

    assert model.calls == 1
    assert [message.body for message in messages] == [
        "only first",
        "tasks template b",
        "mail template c",
    ]
    assert "line mismatch" in caplog.text


@pytest.mark.asyncio
async def test_briefing_hook_collects_sections_and_routes_as_needs_llm() -> None:
    registry = ToolRegistry(FakeEmbedder())
    registry.register(
        ModuleManifest(
            name="calendar",
            version="0.1.0",
            description="Calendar.",
        )
    )
    registry.register(
        ModuleManifest(
            name="tasks",
            version="0.1.0",
            description="Tasks.",
        )
    )
    check_ref = build_briefing_check(
        registry,
        {
            "calendar": lambda: {"next": "standup"},
            "tasks": lambda: {"due": 2},
        },
    )

    result = check_ref()
    manifest = briefing_manifest(check_ref)
    hook = manifest.proactive_hooks[0]
    assert result.payload["sections"] == {
        "calendar": {"next": "standup"},
        "tasks": {"due": 2},
    }
    assert result.dedup_value == datetime.now().date().isoformat()
    assert hook.needs_llm is True
    assert hook.tier == 0
    assert hook.cron == "30 7 * * *"

    model = FakeModelPort(["daily briefing"])
    handler = HitHandler(model, _templates(), DeliverSpy())
    messages = await handler.handle(
        _tick(
            Hit(
                module=manifest.name,
                hook_name=hook.name,
                tier=0,
                urgency="normal",
                needs_llm=hook.needs_llm,
                dedup_key=hook.dedup_key,
                result=result,
                delivery=hook.delivery,
            )
        )
    )

    assert model.calls == 1
    assert messages[0].body == "daily briefing"
