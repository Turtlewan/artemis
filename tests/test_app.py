"""Tests for the app runner + console transport."""

from __future__ import annotations

from collections.abc import Sequence

from artemis.app import App, build_app
from artemis.ports.transport import TransportPort
from artemis.transport import ConsoleTransport
from artemis.types import Message, ModelResponse, OutboundMessage, ScheduledJob, Usage


class FakeModel:
    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = outputs or ["acted"]
        self._act = 0

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, model, temperature, max_tokens
        if response_schema is not None:
            return ModelResponse(
                text='{"steps":["s"]}',
                model_id="fake",
                structured={"steps": ["s"]},
                finish_reason="stop",
                usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )
        out = self.outputs[self._act]
        self._act += 1
        return ModelResponse(
            text=out,
            model_id="fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def test_console_transport_satisfies_port() -> None:
    assert isinstance(ConsoleTransport(), TransportPort)


async def test_console_transport_renders_proactive() -> None:
    lines: list[str] = []
    t = ConsoleTransport(write=lines.append)
    await t.send(OutboundMessage(transport="console", identity="owner", text="hi", proactive=True))
    assert lines == ["[proactive] -> owner: hi"]


def test_build_app_wires_scheduler_and_worker() -> None:
    app = build_app(model=FakeModel(), transport=ConsoleTransport())
    assert isinstance(app, App)


async def test_seeded_job_prints_to_console() -> None:
    lines: list[str] = []
    app = build_app(
        model=FakeModel(["the digest"]),
        transport=ConsoleTransport(write=lines.append),
        owner_identity="owner",
        db_path=":memory:",
    )
    await app.scheduler.schedule(
        ScheduledJob(
            id="m",
            cron=None,
            run_at="2024-01-01T00:00:00",  # past -> due now
            payload={"goal": "digest", "title": "Good morning"},
        )
    )
    await app.scheduler.run(iterations=1)
    assert lines == ["[proactive] -> owner: Good morning\n\nthe digest"]
