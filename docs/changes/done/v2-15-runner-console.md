---
slice: 3
status: ready
coder_effort: medium
---

# v2-15 — Runner + console transport (Artemis runs as a process)

**Identity:** Third Slice-3 spec — makes the proactivity loop *actually run*. A `ConsoleTransport` (the first real `TransportPort`, stdout) + an `App` that composes `build_model_router` + `build_proactive_worker` + `build_scheduler` and calls `scheduler.run()` + an `artemis` console-script entry point. After this, `uv run artemis` is a live always-on heartbeat on the dev box that prints proactive messages when jobs fire — no bot/token setup. (Telegram is the sibling next spec; it drops in as another `TransportPort`.)

Dev-machine-first: fully buildable + hermetically testable on the Windows box; a live run uses the local Ollama backend already in the dev model stack.

## Files to change

1. `src/artemis/transport/__init__.py` — **create**: exports.
2. `src/artemis/transport/console.py` — **create**: `ConsoleTransport` (real `TransportPort`, stdout, injectable writer).
3. `src/artemis/app.py` — **create**: `App` + `build_app` factory + `main()` console-script entry.
4. `pyproject.toml` — **modify**: add `[project.scripts] artemis = "artemis.app:main"`.
5. `tests/test_app.py` — **create**: console transport + `build_app` wiring + end-to-end "scheduled job prints to console" tests.

One cohesive vertical ("Artemis runs and pushes") → a single logical phase.

## Exact changes

### 1. `src/artemis/transport/__init__.py`
```python
"""Transport adapters (egress/ingress surfaces) behind TransportPort."""

from __future__ import annotations

from artemis.transport.console import ConsoleTransport

__all__ = ["ConsoleTransport"]
```

### 2. `src/artemis/transport/console.py`

A real `TransportPort` that renders outbound messages to stdout. No inbound stream on the console in this slice (`receive` is an empty async iterator). `write` is injectable so tests capture instead of printing.

```python
"""Console transport: render outbound messages to stdout (dev/fallback surface)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from artemis.types import InboundMessage, OutboundMessage


class ConsoleTransport:
    name = "console"

    def __init__(self, *, write: Callable[[str], None] = print) -> None:
        self._write = write

    def receive(self) -> AsyncIterator[InboundMessage]:
        async def _empty() -> AsyncIterator[InboundMessage]:
            return
            yield  # pragma: no cover

        return _empty()

    async def send(self, msg: OutboundMessage) -> None:
        tag = "[proactive]" if msg.proactive else "[reply]"
        self._write(f"{tag} -> {msg.identity}: {msg.text}")
```

### 3. `src/artemis/app.py`

Composes the whole loop. `model` and `transport` are injectable seams (default: the real router + console) so tests inject fakes; `App.run()` is the always-on call. `main()` is the console-script glue.

```python
"""Compose and run the Artemis proactivity loop."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from artemis.model.compose import build_model_router
from artemis.ports.model import ModelPort
from artemis.ports.transport import TransportPort
from artemis.proactivity import ProactiveWorker, build_proactive_worker
from artemis.scheduler import DurableScheduler, build_scheduler
from artemis.transport import ConsoleTransport


@dataclass
class App:
    scheduler: DurableScheduler
    worker: ProactiveWorker

    async def run(self) -> None:
        """Start the always-on heartbeat (runs until cancelled)."""
        await self.scheduler.run()


def build_app(
    *,
    db_path: str = ":memory:",
    owner_identity: str = "console",
    model: ModelPort | None = None,
    transport: TransportPort | None = None,
    anthropic_api_key: str | None = None,
    tick_seconds: float = 1.0,
) -> App:
    router = model if model is not None else build_model_router(anthropic_api_key=anthropic_api_key)
    surface = transport if transport is not None else ConsoleTransport()
    worker = build_proactive_worker(model=router, transport=surface, owner_identity=owner_identity)
    scheduler = build_scheduler(
        dispatch=worker.run_job, db_path=db_path, tick_seconds=tick_seconds
    )
    return App(scheduler=scheduler, worker=worker)


def main() -> None:
    """Console-script entry: run the loop with a file-backed schedule + console transport."""
    db_path = os.environ.get("ARTEMIS_DB", "scheduler.db")
    app = build_app(db_path=db_path)
    asyncio.run(app.run())
```

### 4. `pyproject.toml`

Add a scripts table (place it directly after the `dependencies` line / before `[dependency-groups]`):
```toml
[project.scripts]
artemis = "artemis.app:main"
```

### 5. `tests/test_app.py`

`FakeModel` reused from the spine/worker test shape. A capturing list stands in for `print`. The headline test seeds a past-due `run_at` job and asserts the console captured the proactive line — the loop, end to end, through real `ConsoleTransport`.

```python
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
```

Notes for the coder:
- `build_app` constructs `build_model_router()` lazily only when no `model` is injected — constructing providers is import-cheap and does no network, but tests always inject `FakeModel` to avoid any real backend call.
- `App.run()` delegates to `scheduler.run()` (unbounded); tests drive `app.scheduler.run(iterations=1)` directly. Do not add a bounded path to `App.run` itself.
- `ARTEMIS_DB` env override + default `"scheduler.db"` is intentionally minimal; a real data-root layout is a later concern, not this spec.

## Acceptance criteria

1. `ConsoleTransport` structurally satisfies `TransportPort` → `test_console_transport_satisfies_port` passes.
2. Proactive vs reply tagging renders correctly → `test_console_transport_renders_proactive` passes.
3. `build_app` returns a wired `App` (scheduler + worker) → `test_build_app_wires_scheduler_and_worker` passes.
4. **End-to-end through a real transport:** a seeded due job fires through the heartbeat and prints the proactive line to the console writer → `test_seeded_job_prints_to_console` passes.
5. The `artemis` console script resolves: `uv run artemis --help` is not required, but `uv run python -c "from artemis.app import main"` exits 0 and the entry point is registered in `pyproject.toml`.
6. Full-project verify green: `uv run mypy` (strict, 0 errors) + `uv run pytest -q` (all pass) + `uv run ruff check` + `uv run ruff format --check` clean on the new files.

## Commands to run

```bash
uv sync
uv run ruff format src/artemis/transport src/artemis/app.py tests/test_app.py
uv run ruff check src/artemis/transport src/artemis/app.py tests/test_app.py
uv run mypy
uv run pytest -q
```
