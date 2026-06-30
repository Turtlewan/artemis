---
slice: client-revival
status: ready
coder_effort: medium
---

# CR-4 — Layout persistence (cards stay where you drag them)

**Identity:** Fourth client-revival slice — `GET/PUT /app/layout` so the travel-zoom map remembers card positions (last-writer-wins). Ports the self-contained v1 `app_layout_store.py` (pydantic + stdlib only) verbatim, with `default_layout` reseeded to the client's real 11 domains/clusters (`client/src/domains.ts`). Session-gated; no-lock (no unlock check).

## Files to change

1. `src/artemis/api/layout_store.py` — **create**: port `CardPlacement`, `LayoutDTO`, `LayoutStore`, `default_layout` from `archive/v1:src/artemis/app_layout_store.py`, reseeding `default_layout`.
2. `src/artemis/api/app.py` — **modify**: instantiate `LayoutStore(<data_dir>/layout.json)` on `app.state`, add `GET /app/layout` + `PUT /app/layout` (session-gated). Leave auth/ask/status/healthz unchanged.
3. `tests/test_api_layout.py` — **create**: GET-returns-default, PUT-then-GET round-trip, LWW-rejects-stale (via `dependency_overrides[require_session]`).

One cohesive vertical → a single logical phase.

## Exact changes

### 1. `src/artemis/api/layout_store.py`
Port `CardPlacement`, `LayoutDTO`, `LayoutStore` **verbatim** from `archive/v1:src/artemis/app_layout_store.py` (the module is self-contained — `pydantic` + `json`/`os`/`secrets`/`datetime`/`pathlib`). Models:
- `CardPlacement`: `{id: str, domain: str, cluster: str, x: int, y: int, w: int, h: int}` (`extra="forbid"`).
- `LayoutDTO`: `{version: int, updated_at: datetime, cards: list[CardPlacement]}` (`extra="forbid"`).
- `LayoutStore`: atomic JSON file (`get` → `LayoutDTO | None`; `put` → LWW on `updated_at`, stamps server `now()` on accept, atomic temp-file replace).

**Reseed `default_layout()`** to the client's actual domains/clusters from `client/src/domains.ts` (grid units, w=2 h=2, non-overlapping, grouped by cluster):
```python
def default_layout() -> LayoutDTO:
    now = datetime.now(UTC)
    seed = [
        ("email", "Comms", 0, 0), ("people", "Comms", 2, 0),
        ("schedule", "Planning", 0, 2), ("tasks", "Planning", 2, 2),
        ("projects", "Planning", 4, 2), ("travel", "Planning", 6, 2),
        ("memory", "Knowledge", 0, 4), ("knowledge", "Knowledge", 2, 4),
        ("review", "Knowledge", 4, 4),
        ("health", "Self", 0, 6), ("finance", "Self", 2, 6),
    ]
    return LayoutDTO(
        version=1,
        updated_at=now,
        cards=[
            CardPlacement(id=d, domain=d, cluster=c, x=x, y=y, w=2, h=2)
            for (d, c, x, y) in seed
        ],
    )
```

### 2. `src/artemis/api/app.py`
- In `create_app`, after the data_dir is resolved, set `app.state.layout_store = LayoutStore(Path(data_dir) / "layout.json")` (import `LayoutStore` + `default_layout` + `LayoutDTO`, and `Path`).
- Add the two routes on the existing `/app` surface (use the app's router/pattern consistent with `/app/status`), both `Depends(require_session)`:
```python
@app_router.get("/layout", response_model=LayoutDTO)
async def get_layout(request: Request, _p: Principal = Depends(require_session)) -> LayoutDTO:
    store: LayoutStore = request.app.state.layout_store
    return store.get() or default_layout()


@app_router.put("/layout", response_model=LayoutDTO)
async def put_layout(
    body: LayoutDTO, request: Request, _p: Principal = Depends(require_session)
) -> LayoutDTO:
    store: LayoutStore = request.app.state.layout_store
    return store.put(body)
```
(Match the actual router variable + `Principal`/`require_session` import already used by `/app/status` in this file.)

### 3. `tests/test_api_layout.py`
```python
"""Tests for layout persistence."""

from __future__ import annotations

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session


def _client(tmp_path: object) -> TestClient:
    app = create_app(data_dir=str(tmp_path))
    app.dependency_overrides[require_session] = lambda: Principal(device_id="d", person_id="owner")
    return TestClient(app)


def test_get_returns_default_layout(tmp_path: object) -> None:
    resp = _client(tmp_path).get("/app/layout")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 1
    ids = {c["id"] for c in body["cards"]}
    assert "email" in ids and "finance" in ids and len(body["cards"]) == 11


def test_put_then_get_roundtrips(tmp_path: object) -> None:
    client = _client(tmp_path)
    layout = {
        "version": 2,
        "updated_at": "2030-01-01T00:00:00Z",
        "cards": [{"id": "email", "domain": "email", "cluster": "Comms", "x": 5, "y": 6, "w": 2, "h": 2}],
    }
    put = client.put("/app/layout", json=layout)
    assert put.status_code == 200
    got = client.get("/app/layout").json()
    assert len(got["cards"]) == 1
    assert got["cards"][0]["x"] == 5


def test_lww_rejects_stale(tmp_path: object) -> None:
    client = _client(tmp_path)
    newer = {
        "version": 3,
        "updated_at": "2030-06-01T00:00:00Z",
        "cards": [{"id": "tasks", "domain": "tasks", "cluster": "Planning", "x": 1, "y": 1, "w": 2, "h": 2}],
    }
    client.put("/app/layout", json=newer)
    stale = {
        "version": 4,
        "updated_at": "2020-01-01T00:00:00Z",
        "cards": [{"id": "email", "domain": "email", "cluster": "Comms", "x": 9, "y": 9, "w": 2, "h": 2}],
    }
    client.put("/app/layout", json=stale)
    got = client.get("/app/layout").json()
    assert got["cards"][0]["id"] == "tasks"  # stale put rejected


def test_layout_requires_session(tmp_path: object) -> None:
    app = create_app(data_dir=str(tmp_path))
    assert TestClient(app).get("/app/layout").status_code == 401
```

Notes for the coder:
- Match the real `Principal` constructor + `require_session`/router symbols already in `api/app.py` and `api/auth.py`.
- `put` stamps a fresh server `updated_at` on accept, so the stale-rejection test relies on the store's LWW comparing the *incoming* `updated_at` against the stored one — keep the v1 logic verbatim.

## Acceptance criteria

1. `GET /app/layout` with no stored file → the 11-domain default (ids incl. `email`…`finance`) → `test_get_returns_default_layout` passes.
2. `PUT` then `GET` round-trips the cards → `test_put_then_get_roundtrips` passes.
3. A `PUT` with an older `updated_at` is rejected (LWW) → `test_lww_rejects_stale` passes.
4. Both routes require a session (`401` without bearer) → `test_layout_requires_session` passes.
5. Full-project verify green: `uv run mypy` (strict) + `uv run pytest -q` + `uv run ruff check` + `uv run ruff format --check`.

## Commands to run

```bash
uv run ruff format src/artemis/api tests/test_api_layout.py
uv run ruff check src/artemis/api tests/test_api_layout.py
uv run mypy
uv run pytest -q
```
