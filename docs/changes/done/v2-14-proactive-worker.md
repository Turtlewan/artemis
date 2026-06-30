---
slice: 3
status: ready
coder_effort: medium
---

# v2-14 — Proactive worker (scheduler dispatch → spine → transport)

**Identity:** Second Slice-3 spec — the worker that makes Artemis *act*. Wires the scheduler's injected `dispatch` seam (from v2-13) to the `Spine`: a fired job payload → a `Task` → `Spine.run` → a **proactive** `OutboundMessage` pushed out a `TransportPort`. This closes the time-based proactivity loop end-to-end (clock → job → reasoning → push).

Architecture §6 honored: the worker's output is a **proactive suggestion to the owner** (`OutboundMessage.proactive=True`) — the "suggests/asks" posture. External-effect actions (the spine acting on the *world*) are out of scope: the current `Spine` produces text only, so the human-in-the-loop gate for tool execution is a future seam, noted below.

## Files to change

1. `src/artemis/proactivity/__init__.py` — **create**: module exports.
2. `src/artemis/proactivity/worker.py` — **create**: `ProactiveJob` (payload contract) + `ProactiveWorker` + `build_proactive_worker` factory.
3. `tests/test_proactive_worker.py` — **create**: unit + the end-to-end scheduler→worker→spine→transport integration test.

One cohesive new module (`proactivity/`) + its test → a single logical phase.

## Exact changes

### 1. `src/artemis/proactivity/__init__.py`
```python
"""Proactivity: run scheduled/triggered jobs through the spine and push results out."""

from __future__ import annotations

from artemis.proactivity.worker import ProactiveJob, ProactiveWorker, build_proactive_worker

__all__ = ["ProactiveJob", "ProactiveWorker", "build_proactive_worker"]
```

### 2. `src/artemis/proactivity/worker.py`

`ProactiveJob` is the agreed shape of a `ScheduledJob.payload` for proactive work (whoever schedules a job writes a dict matching it). The worker validates the payload, runs the spine **without an acceptance gate** (proactive work is generation, not verification — so it completes in one pass; per-job acceptance is a future option), and pushes any non-empty output as a proactive message.

```python
"""The proactive worker: a fired job payload -> spine run -> proactive push."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from pydantic import BaseModel

from artemis.ports.model import ModelPort
from artemis.ports.transport import TransportPort
from artemis.spine.spine import Spine
from artemis.spine.types import Task
from artemis.types import OutboundMessage


class ProactiveJob(BaseModel):
    """Payload contract for a proactive job carried in ScheduledJob.payload."""

    goal: str
    context: str = ""
    title: str | None = None  # optional label, e.g. "Morning digest"


class ProactiveWorker:
    """Runs a proactive job through the spine and pushes the result to the owner."""

    def __init__(
        self,
        spine: Spine,
        transport: TransportPort,
        *,
        owner_identity: str,
        new_id: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self._spine = spine
        self._transport = transport
        self._owner_identity = owner_identity
        self._new_id = new_id

    async def run_job(self, payload: dict) -> None:  # type: ignore[type-arg]
        """The dispatch sink handed to the scheduler (matches Callable[[dict], Awaitable[None]])."""
        job = ProactiveJob.model_validate(payload)
        task = Task(id=self._new_id(), goal=job.goal, context=job.context)
        result = await self._spine.run(task)
        text = result.output
        if not text:
            return  # nothing worth pushing
        if job.title:
            text = f"{job.title}\n\n{text}"
        await self._transport.send(
            OutboundMessage(
                transport=self._transport.name,
                identity=self._owner_identity,
                text=text,
                proactive=True,
            )
        )


def build_proactive_worker(
    *,
    model: ModelPort,
    transport: TransportPort,
    owner_identity: str,
) -> ProactiveWorker:
    """Factory: a spine over the model router + a transport = a dispatchable worker."""
    return ProactiveWorker(Spine(model), transport, owner_identity=owner_identity)
```

Wiring (for the next spec / a runner; documented, not built here):
```python
worker = build_proactive_worker(model=router, transport=telegram, owner_identity="<chat-id>")
scheduler = build_scheduler(dispatch=worker.run_job, db_path="<data-root>/scheduler.db")
# await scheduler.run()  # heartbeat now drives real spine runs and pushes results
```

Notes for the coder:
- `run_job` deliberately matches the scheduler's `Dispatch = Callable[[dict], Awaitable[None]]` so `dispatch=worker.run_job` type-checks with no adapter.
- Single transport + single `owner_identity` is intentional for this slice (single-user hub). Multi-transport / multi-recipient routing is a later concern; do not add a router here.
- **Gate seam (do not build):** when `Spine` later executes world-changing tools, those calls route through the human-in-the-loop gate before the proactive push — not relevant while the spine emits text only.

### 3. `tests/test_proactive_worker.py`

Reuse the `FakeModel` shape from `tests/test_spine.py` (plan call returns the steps schema; act call returns the next queued output). A `FakeTransport` records sent messages. The headline test schedules a real `DurableScheduler` job whose dispatch is `worker.run_job` and asserts a proactive message lands — the full time-based loop.

```python
"""Tests for the proactive worker (scheduler dispatch -> spine -> transport)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from artemis.proactivity import ProactiveWorker, build_proactive_worker
from artemis.ports.transport import TransportPort
from artemis.scheduler import DurableScheduler, ScheduleLedger
from artemis.spine.spine import Spine
from artemis.types import InboundMessage, Message, ModelResponse, OutboundMessage, Usage
from artemis.types import ScheduledJob

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
        model=FakeModel(),  # type: ignore[arg-type]
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
```

## Acceptance criteria

1. `ProactiveWorker.run_job` sends exactly one proactive `OutboundMessage` with the spine output → `test_run_job_sends_proactive_message` passes.
2. A `title` prefixes the pushed text → `test_title_prefixes_text` passes.
3. Empty spine output pushes nothing → `test_empty_output_sends_nothing` passes.
4. `build_proactive_worker` returns a wired worker → `test_build_proactive_worker_factory` passes.
5. **End-to-end loop:** a due `ScheduledJob` dispatched into the worker drives a spine run and pushes a proactive message → `test_scheduled_job_drives_spine_and_pushes` passes.
6. `FakeTransport` structurally satisfies `TransportPort` → `test_fake_transport_satisfies_port` passes.
7. `worker.run_job` is assignable to the scheduler's `dispatch` parameter with no adapter (verified by the integration test type-checking under strict mypy).
8. Full-project verify green: `uv run mypy` (strict, 0 errors) + `uv run pytest -q` (all pass) + `uv run ruff check` + `uv run ruff format --check` clean on the new files.

## Commands to run

```bash
uv run ruff format src/artemis/proactivity tests/test_proactive_worker.py
uv run ruff check src/artemis/proactivity tests/test_proactive_worker.py
uv run mypy
uv run pytest -q
```
