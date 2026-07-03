# data-wiring — wire the data spine into the ask path (Wave 2a)

**Identity:** Wire `DataStore` onto `app.state` and add the native read short-circuit to `/app/ask`
— an ask tries the local read path first, falling through to the existing selector/router path on
a decline (None). ADR-046 #1/#4. Depends on `data-store` + `data-read` (shipped). This is the spec
that makes the local read path *live*.

The read short-circuit runs BEFORE the capability selector, so a synced-domain ask with fresh local
data answers locally (~2–4s); with no/empty/stale data it falls through to today's invoke path
(graceful degradation). `IngestService`/scheduler wiring is Wave 2b (the store stays empty until
then — 2a is tested by seeding the store directly).

## Files to change
| Op | Path |
|----|------|
| modify | `src/artemis/api/app.py` |
| modify | `src/artemis/api/ask_routes.py` |
| create | `tests/api/test_ask_read.py` |

## Exact changes

### Task 1 — `src/artemis/api/app.py` (modify)
Add the import (with the other `artemis.*` imports, alphabetical-ish near the capabilities imports):
```python
from artemis.data.store import DataStore
```
In `create_app`, immediately after the `app.state.invokes = {}` line (currently line 77), add:
```python
    app.state.data_store = DataStore(str(resolved_data_dir / "spine.db"))
```
Nothing else in app.py changes. (IngestService/scheduler wiring is Wave 2b.)

### Task 2 — `src/artemis/api/ask_routes.py` (modify)
**a. Imports** — add near the other `artemis.*` imports:
```python
from artemis.data.read import ReadService
from artemis.data.store import DataStore
```

**b. New dependency provider** — add beside `_quarantine_reader` (mirrors it: fresh haiku port,
store singleton from app.state):
```python
def _read_service(request: Request) -> ReadService:
    store: DataStore = request.app.state.data_store
    return ReadService(store, phraser=ModelClient(ClaudeCodeProvider(), model_default="haiku"))
```

**c. Short-circuit** — change `_invoke_or_routed_answer` to take a `read_service` and try it first.
Add the parameter and the leading block:
```python
async def _invoke_or_routed_answer(
    *,
    read_service: ReadService,
    selector: CapabilitySelector,
    capability_store: FileCapabilityStore,
    invokes: dict[str, InvokeState],
    model: ModelPort,
    intent_router: IntentRouter,
    secrets: SecretStorePort,
    text: str,
) -> AskResponse:
    local = await read_service.read(text)
    if local is not None:
        return AskResponse(
            text=local.answer, path="local_read", tool_used=None, escalated=False
        )

    selection = await selector.select(text)
    ...  # rest unchanged
```

**d. Wire the dependency into both endpoints.** In `ask` and `ask_stream`, add the parameter:
```python
    read_service: ReadService = Depends(_read_service),
```
and pass `read_service=read_service,` in their `_invoke_or_routed_answer(...)` calls. (The
`confirm_invoke_route` and `ask_voice` endpoints are unchanged.)

### Task 3 — `tests/api/test_ask_read.py` (create)
Mirror the harness in `tests/api/test_ask_routes.py` (its `create_app` + `dependency_overrides`
pattern, `require_session` override, `FixedSelector(_no_match())`, `FakeModel`). A `FakePhraser`
(as in `tests/data/test_read.py`) backs the injected `ReadService`. Cover:

```python
# Reuse the module's existing helpers where possible (import or re-declare FakeModel /
# FixedSelector / _no_match / a session-principal override to match test_ask_routes.py).

def _app_with_read(tmp_path, *, phraser, seed):
    app = create_app(data_dir=tmp_path, model=FakeModel("router answer", "gpt-5.5"))
    if seed is not None:
        app.state.data_store.upsert(seed)  # a calendar Record
    app.dependency_overrides[require_session] = lambda: Principal(device_id="d", session_id="s")
    app.dependency_overrides[ask_routes._read_service] = lambda: ReadService(
        app.state.data_store, phraser=phraser
    )
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(_no_match())
    return app


def test_calendar_ask_answers_from_local_read(tmp_path):
    seed = Record(domain="calendar", kind="event", key="e1", payload={},
                  sanitized_text="Standup 9am", source="calendar-sync", fetched_at=100.0)
    app = _app_with_read(tmp_path, phraser=FakePhraser(answer="You have Standup at 9am."), seed=seed)
    client = TestClient(app)
    resp = client.post("/app/ask", json={"text": "what's on my calendar today"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "local_read"
    assert body["text"] == "You have Standup at 9am."


def test_non_synced_ask_falls_through(tmp_path):
    # read declines (no calendar keyword) -> normal path; selector no-match -> router answer
    app = _app_with_read(tmp_path, phraser=FakePhraser(), seed=None)
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter("plain_ask")
    client = TestClient(app)
    resp = client.post("/app/ask", json={"text": "what is the capital of France"})
    assert resp.status_code == 200
    assert resp.json()["path"] != "local_read"


def test_empty_store_calendar_ask_falls_through(tmp_path):
    # calendar keyword matches but store empty -> read returns None -> normal path
    app = _app_with_read(tmp_path, phraser=FakePhraser(), seed=None)
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter("plain_ask")
    client = TestClient(app)
    resp = client.post("/app/ask", json={"text": "what's on my calendar"})
    assert resp.status_code == 200
    assert resp.json()["path"] != "local_read"
```
Also extend the existing `create_app`-wiring assertion set: add a check that
`app.state.data_store` is a `DataStore` (either append to
`test_create_app_wires_selector_sandbox_and_invokes` in `test_ask_routes.py` — allowed, it's a
1-line additive assertion — OR assert it in a new test here; prefer the new-file assertion to keep
scope to the three listed files).

## Acceptance criteria
1. A calendar ask with a seeded store answers from the local read path (`path=="local_read"`, phraser output). → `test_calendar_ask_answers_from_local_read`
2. A non-synced ask (no domain keyword) falls through to the normal path (`path != "local_read"`). → `test_non_synced_ask_falls_through`
3. A calendar ask with an empty store falls through (read declines). → `test_empty_store_calendar_ask_falls_through`
4. `create_app` wires `app.state.data_store` as a `DataStore`. → asserted in the new test file
5. Whole-project `uv run mypy src/` clean (strict), `uv run ruff check` clean, full suite green.

## Commands to run
```
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -q tests/api/test_ask_read.py
uv run pytest -q
```
