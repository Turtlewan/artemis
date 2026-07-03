# scheduler-wiring — background fetcher scheduler (Wave 2d)

**Identity:** Run the calendar-sync fetcher on a cadence inside the served brain so the local store
stays synced in the background (sync-not-fetch). ADR-046 #1. Wires the shipped `FetcherRunner` +
`IngestService` + `DurableScheduler` into `create_app`'s `_lifespan`, gated by a new `enable_sync`
flag. `cmd_serve` turns it on; every other `create_app` caller (all tests) leaves it off, so the
scheduler never starts in the test suite.

The scheduler loop lives in the serve process's `_lifespan` (the seam map's documented home) so it
shares `app.state` (data_store, capability_store, sandbox, oauth_broker) in one process. A `*/15`
cron schedules the first fire at the next 15-min boundary (future), so entering the lifespan
registers the job without firing it. Fetches are fail-soft (403 until the owner enables the Calendar
API — the loop just stores nothing and the read path falls through).

## Files to change
| Op | Path |
|----|------|
| modify | `src/artemis/api/app.py` |
| modify | `src/artemis/app.py` |
| create | `tests/api/test_sync_wiring.py` |

## Exact changes

### Task 1 — `src/artemis/api/app.py` (modify)
**a. Imports** — add:
```python
import asyncio
from contextlib import asynccontextmanager, suppress   # suppress is new
```
and with the other `artemis.*` imports:
```python
from artemis.data.fetcher import FetcherRunner
from artemis.data.ingest import IngestService
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.scheduler.scheduler import build_scheduler
from artemis.types import ScheduledJob
```

**b. Job factory + sync builder** — add module-level:
```python
_CALENDAR_SYNC_CRON = "*/15 * * * *"


def _calendar_sync_job() -> ScheduledJob:
    return ScheduledJob(
        id="calendar-sync",
        cron=_CALENDAR_SYNC_CRON,
        run_at=None,
        payload={"kind": "fetch", "capability": "calendar-sync", "args": {}},
    )


def _build_sync(app: FastAPI, resolved_data_dir: Path) -> None:
    """Construct the background sync components onto app.state (no async work here)."""
    reader = ModelClient(ClaudeCodeProvider(), model_default="haiku")
    ingest = IngestService(app.state.data_store, reader=reader)
    fetcher = FetcherRunner(
        capability_store=app.state.capability_store,
        secrets_store=app.state.secrets,
        sandbox=app.state.fetch_sandbox,
        ingest=ingest,
        oauth_broker=app.state.oauth_broker,
    )
    app.state.ingest_service = ingest
    app.state.fetcher_runner = fetcher
    app.state.sync_scheduler = build_scheduler(
        dispatch=fetcher.dispatch,
        db_path=str(resolved_data_dir / "schedule.db"),
        tick_seconds=30.0,
    )
```

**c. `_lifespan`** — replace the placeholder body with the scheduler start/stop:
```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    task: asyncio.Task[None] | None = None
    scheduler = getattr(app.state, "sync_scheduler", None)
    if scheduler is not None:
        await scheduler.schedule(_calendar_sync_job())
        task = asyncio.create_task(scheduler.run())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
```

**d. `create_app` signature + wiring** — add the flag and call `_build_sync`:
```python
def create_app(
    *,
    data_dir: str | Path | None = None,
    model: ModelPort | None = None,
    sandbox: SandboxRunner | None = None,
    secrets: SecretStorePort | None = None,
    enable_sync: bool = False,
) -> FastAPI:
    ...
    app.state.data_store = DataStore(str(resolved_data_dir / "spine.db"))
    if enable_sync:
        _build_sync(app, resolved_data_dir)
    ...
```
(Insert the `if enable_sync` block right after the `app.state.data_store = ...` line.)

### Task 2 — `src/artemis/app.py` (modify)
`cmd_serve` turns sync on:
```python
    uvicorn.run(create_app(enable_sync=True), host="127.0.0.1", port=args.port)
```

### Task 3 — `tests/api/test_sync_wiring.py` (create)
Minimal in-file `FakeModel` (as in `tests/api/test_ask_read.py`). Cover:
```python
from fastapi.testclient import TestClient

from artemis.api.app import _calendar_sync_job, create_app
from artemis.data.fetcher import FetcherRunner
from artemis.scheduler.scheduler import DurableScheduler
# + FakeModel (minimal, returns a ModelResponse), Usage/ModelResponse imports


def test_calendar_sync_job_shape():
    job = _calendar_sync_job()
    assert job.id == "calendar-sync"
    assert job.cron == "*/15 * * * *"
    assert job.payload == {"kind": "fetch", "capability": "calendar-sync", "args": {}}


def test_create_app_no_sync_by_default(tmp_path):
    app = create_app(data_dir=tmp_path, model=FakeModel())
    assert getattr(app.state, "sync_scheduler", None) is None
    assert getattr(app.state, "fetcher_runner", None) is None


def test_create_app_enable_sync_wires_components(tmp_path):
    app = create_app(data_dir=tmp_path, model=FakeModel(), enable_sync=True)
    assert isinstance(app.state.fetcher_runner, FetcherRunner)
    assert isinstance(app.state.sync_scheduler, DurableScheduler)


def test_lifespan_registers_calendar_sync_job(tmp_path):
    app = create_app(data_dir=tmp_path, model=FakeModel(), enable_sync=True)
    with TestClient(app):  # entering runs _lifespan (schedules the job, starts the loop)
        active = app.state.sync_scheduler._ledger.active()
        assert any(row.id == "calendar-sync" for row in active)
    # exiting cancels the loop task cleanly (no hang / no unhandled CancelledError)
```
(The `*/15` cron means the job's next fire is a future 15-min boundary, so it does NOT fire during
the test — no OAuth/sandbox attempt. Use `with TestClient(app):` so lifespan startup+shutdown run.)

## Acceptance criteria
1. `_calendar_sync_job()` returns id `calendar-sync`, cron `*/15 * * * *`, payload `{kind:fetch, capability:calendar-sync, args:{}}`. → `test_calendar_sync_job_shape`
2. `create_app()` (default) wires no scheduler/fetcher — the test suite never starts a sync loop. → `test_create_app_no_sync_by_default`
3. `create_app(enable_sync=True)` wires `fetcher_runner` (FetcherRunner) + `sync_scheduler` (DurableScheduler) onto `app.state`. → `test_create_app_enable_sync_wires_components`
4. Entering the lifespan registers the `calendar-sync` job in the scheduler ledger and exits cleanly (loop cancelled, no hang). → `test_lifespan_registers_calendar_sync_job`
5. Whole-project `uv run mypy src/` clean, `ruff check` + `ruff format --check` clean, full suite green (no new hangs).

## Commands to run
```
uv run ruff check src/ tests/
uv run ruff format --check src/artemis/api/app.py src/artemis/app.py tests/api/test_sync_wiring.py
uv run mypy src/
uv run pytest -q tests/api/test_sync_wiring.py
uv run pytest -q
```
