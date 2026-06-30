---
slice: client-revival
status: ready
coder_effort: medium
---

# CR-1 — Brain HTTP API skeleton

**Identity:** First client-revival slice (roadmap: `docs/v2/client-revival-roadmap.md`). Stands up the v2 brain's HTTP API the Tauri client connects to — a FastAPI app on `127.0.0.1:8030` with `/healthz` and a stub `/app/status`, plus an `artemis serve` CLI command. No auth yet (CR-2); the `/app/status` shape is ported exactly from `archive/v1` so the client's Rust gateway parses it unchanged.

## Files to change

1. `pyproject.toml` — **modify**: add `fastapi` + `uvicorn` to `[project].dependencies`.
2. `src/artemis/api/__init__.py` — **create**: export `create_app`.
3. `src/artemis/api/app.py` — **create**: `create_app()` FastAPI factory + response models + routes.
4. `src/artemis/app.py` — **modify**: add `cmd_serve` + a `serve` subparser (lazy uvicorn import). Leave everything else unchanged.
5. `tests/test_api.py` — **create**: `TestClient` tests for `/healthz` + `/app/status`.

One cohesive "brain API skeleton" vertical → a single logical phase.

## Exact changes

### 1. `pyproject.toml`
Append `"fastapi"` and `"uvicorn"` to `[project].dependencies`:
```toml
dependencies = ["jsonschema>=4", "pydantic>=2", "pyyaml>=6", "anthropic>=0.40", "httpx>=0.27", "croniter>=2", "fastapi>=0.115", "uvicorn>=0.30"]
```
(`fastapi` is typed; `httpx` — already a dep — backs `fastapi.testclient.TestClient`. If `uv run mypy` reports missing stubs for `uvicorn`, add an mypy override block:
```toml
[[tool.mypy.overrides]]
module = ["uvicorn.*"]
ignore_missing_imports = true
```
— but try without first; recent uvicorn ships `py.typed`.)

### 2. `src/artemis/api/__init__.py`
```python
"""Artemis brain HTTP API (the surface the Tauri client connects to)."""

from __future__ import annotations

from artemis.api.app import create_app

__all__ = ["create_app"]
```

### 3. `src/artemis/api/app.py`

`StatusResponse` is ported verbatim from `archive/v1:src/artemis/api_app.py` (fields `connected`, `vault_unlocked`, `device_id`). CR-1 returns an unconnected/unpaired default — real status lands with auth in CR-2. The lifespan is a no-op placeholder for now (composing the router/scheduler into the API process is deferred to a later slice; `artemis run` still owns the proactivity loop).

```python
"""FastAPI application factory for the Artemis brain."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class StatusResponse(BaseModel):
    """Authenticated app status (ported from v1; auth arrives in CR-2)."""

    connected: bool
    vault_unlocked: bool
    device_id: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Placeholder: later slices compose router/memory/scheduler onto app.state here.
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Artemis brain", lifespan=_lifespan)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    app_router = APIRouter(prefix="/app")

    @app_router.get("/status", response_model=StatusResponse)
    async def status() -> StatusResponse:
        return StatusResponse(connected=False, vault_unlocked=False, device_id="")

    app.include_router(app_router)
    return app
```

### 4. `src/artemis/app.py` — add a `serve` command

Add `cmd_serve` (lazy-import `uvicorn` + `create_app` so the heavy web deps don't load for `add`/`list`/`cancel`), and register a `serve` subparser with a `--port`. Do not change `App`, `build_app`, or the other commands.

`cmd_serve`:
```python
def cmd_serve(args: argparse.Namespace) -> None:
    """Run the brain HTTP API the Tauri client connects to."""
    import uvicorn

    from artemis.api import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
```

In `main()`, after the `run` subparser registration, add:
```python
    p_serve = sub.add_parser("serve", help="run the brain HTTP API (for the desktop client)")
    p_serve.add_argument(
        "--port", type=int, default=int(os.environ.get("ARTEMIS_BRAIN_PORT", "8030"))
    )
    p_serve.set_defaults(func=cmd_serve)
```

### 5. `tests/test_api.py`
```python
"""Tests for the brain HTTP API skeleton."""

from __future__ import annotations

from fastapi.testclient import TestClient

from artemis.api import create_app


def test_healthz() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_status_default_unconnected() -> None:
    client = TestClient(create_app())
    resp = client.get("/app/status")
    assert resp.status_code == 200
    assert resp.json() == {"connected": False, "vault_unlocked": False, "device_id": ""}
```

Notes for the coder:
- `TestClient` is synchronous and drives the async routes; no `asyncio` decorator needed.
- Keep `uvicorn`/`create_app` imports **inside** `cmd_serve` (lazy) so `artemis add/list/cancel` don't pay the FastAPI import cost.
- Do not start the scheduler/proactivity loop from the API yet — that composition is a later slice.

## Acceptance criteria

1. `GET /healthz` → 200 `{"status":"ok"}` → `test_healthz` passes.
2. `GET /app/status` → 200 `{"connected":false,"vault_unlocked":false,"device_id":""}` (exact v1 shape) → `test_status_default_unconnected` passes.
3. `artemis serve` is a registered subcommand: `uv run python -c "from artemis.app import cmd_serve"` exits 0 and `--port` defaults to `ARTEMIS_BRAIN_PORT` or 8030.
4. The other CLI commands (`add`/`list`/`cancel`/`run`) still work and do **not** import fastapi/uvicorn at module load (lazy import preserved).
5. Full-project verify green: `uv run mypy` (strict) + `uv run pytest -q` + `uv run ruff check` + `uv run ruff format --check`.

## Commands to run

```bash
uv sync
uv run ruff format src/artemis/api src/artemis/app.py tests/test_api.py
uv run ruff check src/artemis/api src/artemis/app.py tests/test_api.py
uv run mypy
uv run pytest -q
```
