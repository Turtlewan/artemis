# CR-5 — Domain Read Endpoints Port Reference

Port reference for the Artemis v2 brain's `/app/*` "domain read" surface. These endpoints
return **typed-but-EMPTY** payloads so the prebuilt Tauri client's detail screens + glance
cards render without error. There are no real recipes/actions/suggestions yet, so the
mutation endpoints are minimal success stubs.

Sources reconciled:

- **v1 brain** (read via `git show archive/v1:src/artemis/api_app.py`) — read models,
  `DomainReadSource` / `DefaultDomainReadSource` seam, route handlers.
- **Client wire shapes** — `client/src/api/dto.ts` (legacy snake_case, **NOT used by the
  screens**) and `client/src/screens/dtos.ts` (the richer shapes the UI actually parses).

**CLIENT WINS.** Confirmed by reading the client: `screens/useDomainRead.ts` does
`invoke<ScreenDTO>(route)` and parses the wire **directly** into `screens/dtos.ts` — there is
**no api/dto.ts → screens/dtos.ts adapter**. Screen components read the camelCase fields
directly: `CalendarDetail.tsx` → `data?.tasksDueByDay[...]`, `GmailDetail.tsx` →
`data?.needsYou`. So the brain must emit the **`screens/dtos.ts`** field names. The
`CalendarRead`/`TasksRead`/`ProjectsRead`/`GmailRead`/`FinanceRead` definitions in
`api/dto.ts` are effectively dead wire types for these reads (snake_case) and must **not** be
used as the v2 target.

> Note: the screens null-coalesce (`?? []`, `?? {}`), so a snake_case wire wouldn't crash —
> but it would render permanently empty (the camel keys would be `undefined`). Emitting the
> screen shape is strictly correct, not just tolerated.

## Auth (all 15 endpoints)

All endpoints are **session-gated**. v1 used `require_unlocked` (valid session **+** owner
vault unlocked → 423 if locked). **CR-5 target: session-gated, NO lock** — gate on
`require_session` only and drop the vault-unlock check, since empty payloads carry no owner
secrets. (The client still has `LOCK_TIER = "unlocked"` for every domain, but that is a
client-side display tier, not a brain requirement.) No rate-limit on the reads; v1 put
`rate_limited` only on the two `tasks/suggestion/*` POSTs.

Router prefix in v1: `APIRouter(prefix="/app")`.

## Endpoint table

| # | Method | Path | Request model | Response model | Empty/stub return |
|---|--------|------|---------------|----------------|-------------------|
| 1 | GET | `/app/calendar` | — | `CalendarRead` | `{events: [], tasksDueByDay: {}}` |
| 2 | GET | `/app/tasks` | — | `TasksRead` | `{overdue: [], today: [], upcoming: [], suggestions: []}` |
| 3 | GET | `/app/projects` | — | `ProjectsRead` | `{projects: []}` |
| 4 | GET | `/app/email` | — | `GmailRead` | `{needsYou: [], signal: []}` |
| 5 | GET | `/app/finance` | — | `FinanceRead` | see FinanceRead below |
| 6 | GET | `/app/review/pending` | — | `list[ReviewItem]` | `[]` |
| 7 | GET | `/app/review/auto-enabled` | — | `list[ReviewItem]` | `[]` |
| 8 | POST | `/app/review/approve` | `ReviewNameRequest` | `ReviewItem` | echo success stub |
| 9 | POST | `/app/review/reject` | `ReviewNameRequest` | `ReviewItem` | echo success stub |
| 10 | GET | `/app/actions/pending` | — | `list[PendingActionResponse]` | `[]` |
| 11 | POST | `/app/actions/approve` | `ActionIdRequest` | `PendingActionResponse` | echo settled stub |
| 12 | POST | `/app/actions/reject` | `ActionIdRequest` | `PendingActionResponse` | echo settled stub |
| 13 | POST | `/app/tasks/suggestion/accept` | `TaskSuggestionAcceptRequest` | `TaskSuggestionAcceptResponse` | `{task: {}}` |
| 14 | POST | `/app/tasks/suggestion/reject` | `TaskSuggestionRejectRequest` | `{ok: bool}` | `{ok: true}` |

(The five domain reads are reached from the client via Tauri `invoke` command names —
`app_calendar_read`, `app_tasks_read`, `app_projects_read`, `app_gmail_read`,
`app_finance_read`, `app_review_pending` — which the Tauri shell maps to these HTTP paths.)

---

## Response models — field names + types (reconciled to the client)

### 1. CalendarRead  — `/app/calendar`  *(client-driven adjustment)*

Target = `screens/dtos.ts`:

```
CalendarRead:
  events: CalendarEvent[]
  tasksDueByDay: Record<string, { title: string; task_id: string }[]>   # camelCase, array values

CalendarEvent:
  id: str
  title: str
  start: str            # ISO-8601
  end: str
  kind: "event" | "held_tentative"        # Literal (client). v1 brain used free str (fake "meeting" — invalid under client)
  attendees?: str[]     # optional
  rsvp?: "yes" | "no" | "maybe"           # Literal (client). v1 brain used free str (fake "accepted" — invalid)
```

**Empty literal:** `CalendarRead(events=[], tasks_due_by_day={})` →
serialize the field as **`tasksDueByDay`** (camelCase). JSON: `{"events": [], "tasksDueByDay": {}}`.

### 2. TasksRead  — `/app/tasks`  *(top-level names match; item shape is client-driven but irrelevant when empty)*

Target = `screens/dtos.ts`:

```
TasksRead:
  overdue:     { title: str; due: str; task_id: str }[]
  today:       { title: str; due?: str; task_id: str }[]
  upcoming:    { title: str; due?: str; task_id: str }[]
  suggestions: { title: str; suggestion_id: str }[]
```

(v1 brain used `list[str]` for all four — drift, but only inside the items, which never
instantiate when empty.)

**Empty literal:** `TasksRead(overdue=[], today=[], upcoming=[], suggestions=[])` →
JSON `{"overdue": [], "today": [], "upcoming": [], "suggestions": []}`.

### 3. ProjectsRead  — `/app/projects`  *(top-level matches; item shape client-driven)*

Target = `screens/dtos.ts`:

```
ProjectsRead:
  projects: ProjectItem[]

ProjectItem:
  id: str
  name: str
  status: "active" | "blocked" | "done"   # Literal (client). v1 brain used free str
  target?: str
  openTasks: int                          # camelCase. v1 brain used open_tasks
```

**Empty literal:** `ProjectsRead(projects=[])` → JSON `{"projects": []}`.

### 4. GmailRead  — `/app/email`  *(top-level field name is client-driven — matters when empty)*

Target = `screens/dtos.ts`:

```
GmailRead:
  needsYou: { id: str; sender: str; subject: str; why: str }[]   # camelCase. v1 brain used needs_you
  signal:   { id: str; sender: str; subject: str; ts: str }[]
```

**Empty literal:** emit **`needsYou`** (camelCase). JSON: `{"needsYou": [], "signal": []}`.

### 5. FinanceRead  — `/app/finance`  *(top-level names all match; item + nullable shapes client-driven)*

Target = `screens/dtos.ts`:

```
FinanceRead:
  week_total: float
  mtd_total: float
  daily:        { weekday: str; date: str; amount: float | null; is_today: bool }[]
  categories:   { name: str; amount: float; pct: float; color: str }[]
  transactions: { date: str; merchant: str; category: str; amount: float }[]
  bills:        { name: str; when: str; overdue: bool; amount: float; is_sub: bool; paid: bool }[]
  unusual:   { merchant: str; amount: float; why: str } | null     # object|null. v1 brain: list[str]|null
  duplicate: { why: str } | null                                   # object|null. v1 brain: list[str]|null
  ambiguous: { merchant: str; amount: float; why: str } | null     # object|null. v1 brain: list[str]|null
```

**Empty literal** (use `null`, not `[]`, for the three advisory slots — client types them
`object | null`):

```python
FinanceRead(
    week_total=0.0,
    mtd_total=0.0,
    daily=[],
    categories=[],
    transactions=[],
    bills=[],
    unusual=None,
    duplicate=None,
    ambiguous=None,
)
```

JSON: `{"week_total": 0, "mtd_total": 0, "daily": [], "categories": [], "transactions": [], "bills": [], "unusual": null, "duplicate": null, "ambiguous": null}`

> v1's `DefaultDomainReadSource.finance()` returned `unusual=[]` etc. — that satisfies
> api/dto.ts (`string[]|null`) but **not** the screen shape (`object|null`). With CR-5 we never
> populate them, so `null` is the safe value for both.

---

## Mutation / review / action endpoints (can be simple success stubs)

There are no real recipes, pending actions, or suggestions in v2 yet, so these can be
**minimal no-op stubs that echo success**. Models are reusable from v1 as-is (none of these
appear in `screens/dtos.ts` with drift; `ReviewItem` + `PendingAction` come from the client's
`api/dto.ts` / `screens/dtos.ts` and match v1).

### ReviewItem (from `api/dto.ts` — matches v1 exactly, reusable as-is)

```
ReviewItem: { name: str; description: str; status: str; action_class: str; safety: str; explanation: str }
```

- **GET `/app/review/pending`** → `list[ReviewItem]`, stub `[]`.
- **GET `/app/review/auto-enabled`** → `list[ReviewItem]`, stub `[]`.
- **POST `/app/review/approve`** — body `ReviewNameRequest {name: str}` → `ReviewItem`.
  Stub: echo `ReviewItem(name=body.name, description="", status="approved", action_class="",
  safety="", explanation="")`. (v1 raised 409 on unknown name; with no recipes a stub should
  just echo success rather than 409.)
- **POST `/app/review/reject`** — body `ReviewNameRequest {name: str}` → `ReviewItem`.
  Stub: same with `status="rejected"`.

### PendingActionResponse (from `screens/dtos.ts` `PendingAction` — matches v1, reusable as-is)

```
PendingActionResponse / PendingAction:
  id: str; module: str; tool: str; summary: str; action_class: str; status: str
  created_at: datetime (ISO str on wire); expires_at: datetime; result: dict | null
```

- **GET `/app/actions/pending`** → `list[PendingActionResponse]`, stub `[]`.
- **POST `/app/actions/approve`** — body `ActionIdRequest {id: str}` → `PendingActionResponse`.
  Stub: with no staged actions, simplest is a 404 `"action not found"` (matches v1's KeyError
  path); or, if the screen needs a 200, echo a settled `PendingActionResponse(id=body.id,
  module="", tool="", summary="", action_class="", status="approved", created_at=now,
  expires_at=now, result=None)`. **Recommend 404** — the list is always empty, so the client
  never holds an id to approve.
- **POST `/app/actions/reject`** — body `ActionIdRequest {id: str}` → `PendingActionResponse`.
  Same treatment (404, or echo `status="rejected"`).

### Task suggestion accept/reject

```
TaskSuggestionAcceptRequest:  { suggestion_id: str; due_at?: str; project_id?: str }
TaskSuggestionAcceptResponse: { task: dict }                # arbitrary task object
TaskSuggestionRejectRequest:  { suggestion_id: str }
```

- **POST `/app/tasks/suggestion/accept`** → `TaskSuggestionAcceptResponse`.
  Stub: no suggestions exist, so simplest is 404 `"suggestion not found"` (v1 KeyError path).
  If a 200 is needed, echo `TaskSuggestionAcceptResponse(task={})`. **Recommend 404** — the
  client only sends ids it got from `TasksRead.suggestions`, which is empty.
- **POST `/app/tasks/suggestion/reject`** → plain `{ok: bool}` (matches client `OkResponse`).
  Stub: `{"ok": True}` (v1 reject is idempotent — unknown id is a no-op success).

---

## DRIFT SUMMARY (client `screens/dtos.ts` wins everywhere)

| Model | Field | v1 brain (`api_app.py` / `api/dto.ts`) | Client (`screens/dtos.ts`) — WINS | Matters when empty? |
|-------|-------|----------------------------------------|-----------------------------------|---------------------|
| CalendarRead | tasks-due map | `tasks_due_by_day: dict[str,int]` (counts) | `tasksDueByDay: Record<str, {title,task_id}[]>` | **YES** — top-level name + type |
| CalendarEvent | `kind` | free `str` (fake `"meeting"`) | Literal `"event" \| "held_tentative"` | No (item never built) |
| CalendarEvent | `rsvp` | free `str` (fake `"accepted"`) | Literal `"yes" \| "no" \| "maybe"` | No |
| TasksRead | overdue/today/upcoming/suggestions | `list[str]` | arrays of objects (`{title,..,task_id}` / `{title,suggestion_id}`) | No (empty arrays match) |
| ProjectsRead | item `open_tasks` | `open_tasks: int` | `openTasks: int` (camel) | No |
| ProjectItem | `status` | free `str` | Literal `"active" \| "blocked" \| "done"` | No |
| GmailRead | needs list | `needs_you: GmailNeed[]` | `needsYou: {...}[]` (camel) | **YES** — top-level name |
| FinanceRead | unusual/duplicate/ambiguous | `list[str] \| null` (fake `[]`) | `object \| null` | **YES** — emit `null` not `[]` |
| FinanceDaily | item | `{date, amount}` | `{weekday, date, amount\|null, is_today}` | No |
| FinanceCategory | item | `{name, amount, color}` | `{name, amount, pct, color}` | No |
| FinanceTransaction | item | `{id, merchant, amount, date, category}` | `{date, merchant, category, amount}` (no id) | No |
| FinanceBill | item | `{id, name, amount, due}` | `{name, when, overdue, amount, is_sub, paid}` | No |
| Auth gate | all reads | `require_unlocked` (session + vault) | n/a (CR-5: session only, no lock) | n/a |

**Net for empty payloads — only three drifts change the wire even when empty:**
1. `CalendarRead` → field **`tasksDueByDay`** (camel), value `{}` (object, not int-map).
2. `GmailRead` → field **`needsYou`** (camel).
3. `FinanceRead` → `unusual`/`duplicate`/`ambiguous` = **`null`** (not `[]`).
All other drift is inside list items that never instantiate while the lists are empty.

## Reusable as-is vs client-driven adjustment

- **Reusable as-is from v1:** `ReviewItem`, `PendingActionResponse`, `ReviewNameRequest`,
  `ActionIdRequest`, `TaskSuggestionAcceptRequest`, `TaskSuggestionAcceptResponse`,
  `TaskSuggestionRejectRequest`, and the `TasksRead` / `ProjectsRead` **container** shapes
  (only their item interiors differ, irrelevant when empty).
- **Need client-driven adjustment (rebuild against `screens/dtos.ts`):** `CalendarRead`
  (camel `tasksDueByDay` + array values), `GmailRead` (camel `needsYou`), `FinanceRead`
  (object|null advisory slots), and — if ever populated — `CalendarEvent`, `ProjectItem`,
  `FinanceDaily/Category/Transaction/Bill` item shapes.

## Enums / Literal types (client-side, enforce if items are ever populated)

- `CalendarEvent.kind`: `"event" | "held_tentative"`
- `CalendarEvent.rsvp`: `"yes" | "no" | "maybe"`
- `ProjectItem.status`: `"active" | "blocked" | "done"`
- `EngineTag` (used by `GenericRead`, out of CR-5's 5 typed reads): `"local" | "codex" | "review"`

## Out of scope note — GenericRead

The other client domains (`people`, `travel`, `memory`, `knowledge`, `health`) use
`GenericRead { count: int; items: {title, subtitle?, engine?}[] }` and were **not** routes in
v1 `api_app.py`. They are not part of CR-5's ~15 endpoints; if the brain needs to answer their
Tauri commands, the empty literal is `{count: 0, items: []}`.
