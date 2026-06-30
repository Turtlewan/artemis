---
slice: client-revival
status: ready
coder_effort: high
---

# CR-5 — Typed-empty domain reads (every screen renders)

**Identity:** Fifth client-revival slice — the ~15 `/app/*` domain-read + review/actions/suggestion endpoints, returning **well-typed EMPTY payloads** so the client's detail screens and glance cards render without error (empty states / zeros). Real spokes (Gmail/Calendar/Finance integrations) are the CR-7+ tail; this slice is the typed shell. **Critical:** the client parses the wire **directly into `client/src/screens/dtos.ts`** (camelCase, no adapter) — the brain must emit THOSE shapes, not v1's snake_case `api_app` models. Exact field lists + reconciliation: **`docs/findings/cr-5-domain-reads-reference.md`** (read it).

## Files to change

1. `src/artemis/api/domain_routes.py` — **create**: the read/mutation pydantic models (matched to `screens/dtos.ts`) + an `APIRouter` with the ~15 routes.
2. `src/artemis/api/app.py` — **modify**: `include_router` the domain router. Nothing else.
3. `tests/test_api_domains.py` — **create**: each read returns its empty shape with the right (camelCase) keys; mutations behave; `401` without a session.

One cohesive "domain reads" vertical (large by model count, simple by logic) → a single phase.

## Exact changes

### Source of truth for shapes
Define the models to match **`client/src/screens/dtos.ts`** (read it + the findings doc for exact fields). The brain emits camelCase where the client uses it. The **3 drift points that matter even when empty**:
- `CalendarRead.tasksDueByDay` — **camelCase**, a `dict` (Record) of arrays, empty `{}` (NOT v1's int-count map).
- `GmailRead.needsYou` — **camelCase** (NOT `needs_you`).
- `FinanceRead.unusual` / `.duplicate` / `.ambiguous` — default **`null`** (NOT `[]`); the client types them `object | null`.

### Models + empty instances (top-level containers — items never instantiate while empty)
```python
class CalendarRead(BaseModel):
    events: list[CalendarEvent] = Field(default_factory=list)
    tasksDueByDay: dict[str, list[CalendarTaskDue]] = Field(default_factory=dict)  # noqa: N815

class TasksRead(BaseModel):
    overdue: list[TaskItem] = Field(default_factory=list)
    today: list[TaskItem] = Field(default_factory=list)
    upcoming: list[TaskItem] = Field(default_factory=list)
    suggestions: list[TaskSuggestion] = Field(default_factory=list)

class ProjectsRead(BaseModel):
    projects: list[ProjectItem] = Field(default_factory=list)

class GmailRead(BaseModel):
    needsYou: list[GmailNeed] = Field(default_factory=list)  # noqa: N815
    signal: list[GmailSignal] = Field(default_factory=list)

class FinanceRead(BaseModel):
    week_total: float = 0
    mtd_total: float = 0
    daily: list[FinanceDaily] = Field(default_factory=list)
    categories: list[FinanceCategory] = Field(default_factory=list)
    transactions: list[FinanceTransaction] = Field(default_factory=list)
    bills: list[FinanceBill] = Field(default_factory=list)
    unusual: object | None = None
    duplicate: object | None = None
    ambiguous: object | None = None
```
Define the **item models** (`CalendarEvent`, `CalendarTaskDue`, `TaskItem`, `TaskSuggestion`, `ProjectItem`, `GmailNeed`, `GmailSignal`, `FinanceDaily`, `FinanceCategory`, `FinanceTransaction`, `FinanceBill`) with the fields + `Literal` enums listed in the findings doc / `screens/dtos.ts` (so the models are complete + typed), but the routes return the **empty containers** above — items aren't instantiated. Also `ReviewItem` and `PendingActionResponse` (reusable from v1, per the findings doc) + request bodies (`ReviewNameRequest{name}`, `ActionIdRequest{id}`, `TaskSuggestionAcceptRequest{suggestion_id, due_at?, project_id?}`, `TaskSuggestionRejectRequest{suggestion_id}`).

> Use `# noqa: N815` on the camelCase fields if ruff flags mixedCase; they must stay camelCase to match the client wire.

### Routes (all `Depends(require_session)`, prefix `/app`)
- `GET /calendar` → `CalendarRead()`; `GET /tasks` → `TasksRead()`; `GET /projects` → `ProjectsRead()`; `GET /email` → `GmailRead()`; `GET /finance` → `FinanceRead()`.
- `GET /review/pending` → `[]`; `GET /review/auto-enabled` → `[]` (both `list[ReviewItem]`).
- `POST /review/approve` (body `{name}`) → `ReviewItem(name=..., status="approved", ...)`; `POST /review/reject` → `ReviewItem(..., status="rejected")`. (Stub echo — no real recipes yet. Fill the other `ReviewItem` fields with benign defaults per its definition.)
- `GET /actions/pending` → `[]` (`list[PendingActionResponse]`).
- `POST /actions/approve`, `POST /actions/reject` (body `{id}`) → **404** (`HTTPException(404)`) — the pending list is always empty, so the client never holds a valid id.
- `POST /tasks/suggestion/accept` (body `{suggestion_id, due_at?, project_id?}`) → **404** (no real suggestions).
- `POST /tasks/suggestion/reject` (body `{suggestion_id}`) → `{"ok": true}`.

Match the real `Principal`/`require_session` imports + the `/app` router pattern already in the codebase (`api/auth_routes.py` / `api/app.py`).

### `app.py`
`app.include_router(domain_routes.router)` (import it). No other change.

### Tests (`tests/test_api_domains.py`)
Use `dependency_overrides[require_session]` (as in `test_api_ask.py`). Assert the **camelCase keys** explicitly for the drift points.
```python
def test_calendar_empty(...):
    body = client.get("/app/calendar").json()
    assert body == {"events": [], "tasksDueByDay": {}}

def test_email_empty(...):
    assert client.get("/app/email").json() == {"needsYou": [], "signal": []}

def test_finance_empty_has_null_advisories(...):
    body = client.get("/app/finance").json()
    assert body["unusual"] is None and body["duplicate"] is None and body["ambiguous"] is None
    assert body["week_total"] == 0 and body["daily"] == []

def test_tasks_projects_empty(...): ...   # {"overdue":[],...}, {"projects":[]}
def test_review_and_actions_pending_empty(...): ...   # [] and []
def test_review_approve_echoes(...): ...   # status == "approved"
def test_suggestion_reject_ok(...): ...     # {"ok": true}
def test_actions_approve_404(...): ...      # status_code == 404
def test_reads_require_session(...): ...    # GET /app/calendar without override -> 401
```

## Acceptance criteria

1. Each of `/app/{calendar,tasks,projects,email,finance}` returns its empty shape with the **exact client keys** (incl. camelCase `tasksDueByDay`, `needsYou`, and `null` finance advisories).
2. `/app/review/pending`, `/app/review/auto-enabled`, `/app/actions/pending` return `[]`.
3. `review/approve|reject` echo a settled `ReviewItem`; `suggestion/reject` returns `{"ok": true}`; `actions/approve|reject` + `suggestion/accept` return `404`.
4. All routes require a session (`401` without bearer).
5. Full-project verify green: `uv run mypy` (strict) + `uv run pytest -q` + `uv run ruff check` + `uv run ruff format --check`.

## Commands to run

```bash
uv run ruff format src/artemis/api tests/test_api_domains.py
uv run ruff check src/artemis/api tests/test_api_domains.py
uv run mypy
uv run pytest -q
```
