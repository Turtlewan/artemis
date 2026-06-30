"""Tests for the proactive worker (scheduler dispatch -> spine -> transport)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from artemis.proactivity import ProactiveWorker, build_proactive_worker
from artemis.ports.transport import TransportPort
from artemis.scheduler import DurableScheduler, ScheduleLedger
from artemis.spine.spine import Spine
from artemis.types import (
    InboundMessage,
    Message,
    ModelResponse,
    OutboundMessage,
    ScheduledJob,
    Usage,
)

T0 = 1_900_000_000.0


class FakeModel:
    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = outputs or ["acted"]
        self._act_calls = 0

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
                text='{"steps":["draft"]}',
                model_id="fake",
                structured={"steps": ["draft"]},
                finish_reason="stop",
                usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )
        out = self.outputs[self._act_calls]
        self._act_calls += 1
        return ModelResponse(
            text=out,
            model_id="fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FakeTransport:
    name = "fake"

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    def receive(self) -> AsyncIterator[InboundMessage]:
        async def _empty() -> AsyncIterator[InboundMessage]:
            return
            yield  # pragma: no cover

        return _empty()

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


def test_fake_transport_satisfies_port() -> None:
    assert isinstance(FakeTransport(), TransportPort)


async def test_run_job_sends_proactive_message() -> None:
    transport = FakeTransport()
    worker = ProactiveWorker(
        Spine(FakeModel(["digest body"])), transport, owner_identity="owner", new_id=lambda: "fixed"
    )
    await worker.run_job({"goal": "summarize today", "context": "emails"})
    assert len(transport.sent) == 1
    msg = transport.sent[0]
    assert msg.proactive is True
    assert msg.transport == "fake"
    assert msg.identity == "owner"
    assert msg.text == "digest body"


async def test_title_prefixes_text() -> None:
    transport = FakeTransport()
    worker = ProactiveWorker(Spine(FakeModel(["body"])), transport, owner_identity="owner")
    await worker.run_job({"goal": "g", "title": "Morning digest"})
    assert transport.sent[0].text == "Morning digest\n\nbody"


async def test_empty_output_sends_nothing() -> None:
    transport = FakeTransport()
    worker = ProactiveWorker(Spine(FakeModel([""])), transport, owner_identity="owner")
    await worker.run_job({"goal": "g"})
    assert transport.sent == []


def test_build_proactive_worker_factory() -> None:
    transport = FakeTransport()
    worker = build_proactive_worker(
        model=FakeModel(),
        transport=transport,
        owner_identity="owner",
    )
    assert isinstance(worker, ProactiveWorker)


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


async def test_scheduled_job_drives_spine_and_pushes() -> None:
    """End-to-end: a due scheduled job runs through the spine and pushes a proactive message."""
    clock = Clock(T0)
    transport = FakeTransport()
    worker = ProactiveWorker(
        Spine(FakeModel(["the digest"])), transport, owner_identity="owner", new_id=lambda: "id1"
    )
    sched = DurableScheduler(
        ScheduleLedger(":memory:", now=clock), dispatch=worker.run_job, now=clock
    )
    await sched.schedule(
        ScheduledJob(
            id="morning",
            cron=None,
            run_at="2024-01-01T00:00:00",  # in the past relative to T0 -> due
            payload={"goal": "morning digest", "title": "Good morning"},
        )
    )
    await sched.run(iterations=1)
    assert len(transport.sent) == 1
    assert transport.sent[0].proactive is True
    assert transport.sent[0].text == "Good morning\n\nthe digest"
