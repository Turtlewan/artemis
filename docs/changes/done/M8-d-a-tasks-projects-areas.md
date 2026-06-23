---
spec: m8-d-a-tasks-projects-areas
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seams 3, 5, 6) + m8-productivity.md BLOCKs B2, B3, B4, F2; Decision D3 (eager GOAL entity) -->
<!-- Seam 6: GOAL entity created EAGERLY by create_project (Decision D3 2026-06-11) — see Task 2.
     Seam 5: check_ref is sync, payload = ids+counts only — enforced by M8-d-c1; no change here.
     Seam 3: all gated-tool staging uses front-door fq id + _execute twin — no gated tools in M8-d-a
     (all tools are WRITE/READ AUTO per ADR-011 self-only writes); no change required here.
     B2 fix: add clear_task_schedule_link to repository.
     B3 fix: complete_task early-returns if already done; guard uses >=.
     B4 fix: fixed-mode recurrence advances from previous due_at for "every N" rules.
     F2 fix: comment "# all 28 ToolSpecs" corrected to 30. -->

# Spec: M8-d-a — Productivity core: owned SQLCipher schema (areas / projects / tasks / subtasks / recurrence / suggestions) + CRUD tools + recurrence engine + ModuleManifest

**Identity:** The Productivity module's owned SQLCipher data layer and tool surface — schema, repository, all read/write brain tools, recurrence engine (fixed + completion-based), and `ModuleManifest` (OWNER_PRIVATE, no hooks).
→ why: see docs/technical/modules/productivity.md (LOCKED 2026-06-09) · docs/technical/adr/ADR-011-spoke-source-of-truth.md (owned, self-only writes are autonomous, no external sync).

<!-- Split rule: TWO logical phases (1: schema + repository, 2: tools + manifest + recurrence engine). Exceeds 3 files as an unavoidable atomic unit — schema is meaningless without the repository that enforces its FK/status invariants, and the tools are meaningless without both. SPLIT FLAG: if Phase 1 and Phase 2 individually still feel large in context, this spec may be split post-approval into M8-d-a1 (schema+repo) and M8-d-a2 (tools+manifest+recurrence) — the Phase boundary is clean and Tasks 1–3 / Tasks 4–7 are independent after that. Flagged per rules. -->

## Assumptions

- **M0-a** (`Settings`, `get_settings`, `paths.scope_dir`, `relational/` subdir convention from `paths.py` Task 4) is complete. → impact: Stop (DB path derives from `paths.scope_dir(settings, OWNER_PRIVATE) / "relational" / "productivity.db"`).
- **M1-a** (`ModuleManifest`, `ToolSpec`, `ActionRisk`, `DataScope`, `Permissions` from `artemis.manifest`) is complete. → impact: Stop (the manifest is constructed from these exact types).
- **M2-b** (`KeyProvider` Protocol, `SecretKey`, `ScopeLockedError`, `OWNER_PRIVATE` from `artemis.identity.scope`, `FakeKeyProvider`) is complete. → impact: Stop (the store opens only when the owner is unlocked; `ScopeLockedError` propagates exactly as in M8-a).
- **M2-c** (`sqlcipher_open(path, key_hex)` in `artemis.data.sqlcipher`) is complete. → impact: Stop (the store opens the productivity DB via this wrapper; `key.as_hex()` is local-only inside `_connect()` — same pattern as `SqlCipherTokenStore._connect` in M8-a).
- `paths.scope_dir(settings, OWNER_PRIVATE)` returns a `Path`; the `relational/` subdirectory is a valid sibling of `memory/` under the per-scope data dir (established by M0-a Task 4). → impact: Stop (if `relational/` is not an M0-a convention, the DB path must be reconciled; the path is documented as nullable/soft-adjustable in Assumptions per M8-a precedent).
- All productivity data is **owner-authored, fully trusted** — no `artemis.untrusted` layer applies here (except email-sourced `suggestions`, which M8-d-c writes; the `suggestions` table here only holds confirmed/pending rows created by the core CRUD path). → impact: Caution (M8-d-c capture path is NOT built here; the `suggestions` table structure just needs to support it).
- Off-hardware: the keyed SQLCipher open may not be available in CI; tests use a `FakeKeyProvider(owner_unlocked=True)` + a plain-sqlite fallback behind the same `_connect()` seam (mirroring M4-a Task 6 and M8-a Task 7 patterns). The real keyed round-trip is GATED on-hardware. → impact: Caution (same CI pattern as every prior SQLCipher-backed store in this project).
- `calendar_event_id` and `scheduled_block` columns on `tasks` are nullable in M8-d-a; they are written by M8-d-b (time-blocking seam). M8-d-a does NOT implement `task.schedule` — that tool belongs to M8-d-b. → impact: Caution (the columns exist; the write path is deferred).
- The module package lives at `src/artemis/modules/productivity/` — the locked domain-module convention (all spoke modules under `src/artemis/modules/<name>/`). → impact: Stop.
- `ActionRisk.READ` and `ActionRisk.WRITE` are the only risks used here (all owned data; no HIGH_STAKES — self-only writes require no gating per ADR-011). → impact: Low.

Simplicity check: considered combining all CRUD into a single `TaskStore` God class — rejected; a thin `ProductivityRepository` with separate method groups (area/project/task) and a `ProductivityStore` adapter layer is the minimum that lets the tools stay thin (each tool calls one method). No ORM (raw parameterised SQL, same as every other SQLCipher store in this project). No migration framework — `CREATE TABLE IF NOT EXISTS` + schema-version row in `meta`, same as M4-a.

## Prerequisites

- Specs that must be complete first: **M0-a**, **M1-a**, **M2-b**, **M2-c**.
- Specs this enables (not blocking): **M8-d-b** (Calendar seam — requires `calendar_event_id`/`scheduled_block` columns written here), **M8-d-c** (hooks + capture — requires `suggestions` table written here).
- Environment setup required: no new PyPI deps beyond what M0-a/M2-c already introduce (stdlib `sqlite3` path for fallback; real SQLCipher via the M2-c binding). `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/__init__.py` | create | package marker for modules namespace |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` | create | package marker + re-exports (`ProductivityStore`, `productivity_manifest`) |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/schema.py` | create | DDL (`areas`, `projects`, `tasks`, `task_subtasks`, `task_recurrence`, `suggestions`, `meta`), `create_schema(conn)`, `SCHEMA_VERSION`, status/priority/recurrence enums as Python `StrEnum` constants |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/repository.py` | create | `ProductivityRepository` — all CRUD methods for areas, projects, tasks, subtasks, suggestions; recurrence engine (`spawn_next_recurrence`) |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/store.py` | create | `ProductivityStore` — `_connect()` (SQLCipher keyed-open, local `key.as_hex()`), lazy-open wrapper, thin methods delegating to `ProductivityRepository` |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` | create | all `ToolSpec` callables (read + write tools per §D of productivity.md) as thin functions over `ProductivityStore` |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` | create | `productivity_manifest()` → `ModuleManifest`; wires all `ToolSpec`s |
| `/Users/artemis-build/artemis/tests/test_productivity_core.py` | create | schema round-trip, repository CRUD, recurrence engine (both modes), `ScopeLockedError` propagation, tools smoke, manifest shape |

## Tasks

### Phase 1 — Schema + Repository

- [ ] **Task 1: Schema DDL** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/schema.py`, `/Users/artemis-build/artemis/src/artemis/modules/__init__.py`, `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` —

  Python `StrEnum` constants (no SQLite enum enforcement — store as TEXT + CHECK):
  - `TaskStatus`: `TODO = "todo"`, `DOING = "doing"`, `DONE = "done"`, `CANCELLED = "cancelled"`
  - `TaskPriority`: `NONE = "none"`, `LOW = "low"`, `MEDIUM = "medium"`, `HIGH = "high"`
  - `ProjectStatus`: `ACTIVE = "active"`, `ON_HOLD = "on_hold"`, `DONE = "done"`
  - `RecurrenceMode`: `FIXED = "fixed"`, `AFTER_COMPLETION = "after_completion"`

  `SCHEMA_VERSION = "1"`

  `def create_schema(conn) -> None` — idempotent (`CREATE TABLE IF NOT EXISTS`). Tables:

  **`meta`**: `key TEXT PRIMARY KEY, value TEXT NOT NULL` — insert `schema_version`, `created_at` on first call (guard with `INSERT OR IGNORE`).

  **`areas`**: `id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1))`.
  Index: `idx_areas_archived` on `(archived)`.

  **`projects`**: `id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','on_hold','done')), target_date TEXT, notes TEXT, area_id TEXT REFERENCES areas(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)), project_goal_entity_id TEXT` (nullable — stores the `EntityRef.entity_id` of the eagerly-created GOAL entity; `goal:{project_id}` when present; NULL if `EntityRepository` was not available at creation time — Decision D3).
  Indexes: `idx_projects_area_id` on `(area_id)`, `idx_projects_status` on `(status)`.

  **`tasks`**: `id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT, status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','done','cancelled')), priority TEXT NOT NULL DEFAULT 'none' CHECK(priority IN ('none','low','medium','high')), tags TEXT NOT NULL DEFAULT '[]'` (JSON array text), `project_id TEXT REFERENCES projects(id), area_id TEXT REFERENCES areas(id), estimate_minutes INTEGER, due_at TEXT, scheduled_block TEXT, calendar_event_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT`.
  Indexes: `idx_tasks_project_id` on `(project_id)`, `idx_tasks_area_id` on `(area_id)`, `idx_tasks_status` on `(status)`, `idx_tasks_due_at` on `(due_at)` WHERE `status NOT IN ('done','cancelled')`.

  **`task_subtasks`**: `id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0,1)), position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL`.
  Index: `idx_task_subtasks_task_id` on `(task_id)`.

  **`task_recurrence`**: `task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, mode TEXT NOT NULL CHECK(mode IN ('fixed','after_completion')), rule TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL`.
  (One row per recurring task. `rule` = an RRULE-compatible string or a simple interval descriptor — see repository Task 2 for interpretation. Index: covered by PK.)

  **`suggestions`**: `id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT, source TEXT NOT NULL DEFAULT 'manual'` (e.g. `"chat"`, `"email"`, `"calendar"`), `raw_context TEXT, commitment_shape TEXT, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL`. (`commitment_shape` stores the normalised commitment verb e.g. `"will_send"` from `COMMITMENT_SCHEMA`; `NULL` for manually-created suggestions — U7 fix to avoid encoding machine state in the `notes` field.)
  Index: `idx_suggestions_status` on `(status)`.

  Enable FK enforcement on every connection: `PRAGMA foreign_keys = ON`.

  — done when: `uv run mypy --strict src` passes; `create_schema` on a fresh in-memory sqlite3 connection creates all 7 tables and all indexes, verified by querying `sqlite_master`; `create_schema` called twice is idempotent (no error).

- [ ] **Task 2: Repository** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/repository.py` —

  `class ProductivityRepository` constructed with `(conn)`. All SQL parameterised (no string interpolation of values). All writes return the affected `id`. Timestamps as ISO-8601 UTC text (`now_iso()` = `datetime.now(timezone.utc).isoformat()` — uses timezone-aware datetime; yields `+00:00` suffix, which is valid ISO-8601 UTC; do NOT append a literal `"Z"` separately). All IDs are `uuid4()` hex strings.

  **Areas:**
  - `create_area(title, notes=None) -> str`
  - `get_area(id) -> dict | None`
  - `list_areas(*, include_archived=False) -> list[dict]`
  - `update_area(id, *, title=None, notes=None) -> None` (only non-None kwargs written; always updates `updated_at`)
  - `archive_area(id) -> None` (sets `archived=1`; does NOT cascade — projects/tasks keep their `area_id` for history)

  **Projects:**
  - `create_project(title, *, notes=None, area_id=None, target_date=None, entity_repo: EntityRepository | None = None) -> str` — after inserting the project row, if `entity_repo` is provided (non-None), calls `entity_repo.resolve_or_create_entity(name=title, entity_type=EntityType.GOAL, entity_id=f"goal:{project_id}")` and stores the returned `EntityRef` in a new `project_goal_entity_id` column on the `projects` table (nullable TEXT; stores `entity_ref.entity_id`). **Decision D3 (2026-06-11): every project is cross-module-linkable at creation** (contracts.md Seam 6). If `entity_repo is None` (off-hardware / tests without M4-d), the GOAL creation is skipped and `project_goal_entity_id` is NULL — degrade-don't-crash. (The `project_goal_entity_id TEXT` column is defined in the Task 1 `projects` DDL.)
  - `get_project(id) -> dict | None`
  - `list_projects(*, status=None, area_id=None, include_archived=False) -> list[dict]`
  - `update_project(id, *, title=None, notes=None, status=None, target_date=None, area_id=None) -> None`
  - `archive_project(id) -> None`
  - `project_tasks(project_id) -> list[dict]` (active tasks only, status NOT IN ('done','cancelled'))
  - `assign_project_to_area(project_id, area_id) -> None`

  **Tasks:**
  - `create_task(title, *, notes=None, status="todo", priority="none", tags=None, project_id=None, area_id=None, estimate_minutes=None, due_at=None) -> str` — `tags` serialised as JSON; validates status/priority against StrEnum values.
  - `get_task(id) -> dict | None` — includes subtasks (joined or separate query, your choice; document) and recurrence row if present.
  - `list_tasks(*, status=None, project_id=None, area_id=None) -> list[dict]`
  - `search_tasks(query: str) -> list[dict]` — `LIKE '%query%'` on `title || ' ' || COALESCE(notes,'')` (simple, no FTS5 in this store — productivity scale does not warrant it). At most 50 results.
  - `today_tasks() -> list[dict]` — tasks with `due_at <= today` AND `status NOT IN ('done','cancelled')`.
  - `upcoming_tasks(days=7) -> list[dict]` — tasks with `due_at` within the next N days AND active.
  - `overdue_tasks() -> list[dict]` — tasks with `due_at < today` AND `status NOT IN ('done','cancelled')`.
  - `complete_task(id) -> dict | None` — **Early-return if task is already `done` or `cancelled`: load the row first; if `status` is already `'done'` or `'cancelled'`, return `None` immediately (no-op — prevents double-spawn and stale `completed_at` overwrite on retry).** Otherwise, sets `status='done'`, `completed_at=now`; **if the task has a `task_recurrence` row, calls `spawn_next_recurrence(id)` and returns the spawned task dict**; otherwise returns `None`. (Fixes B3.)
  - `cancel_task(id) -> None`
  - `update_task(id, *, title=None, notes=None, priority=None, tags=None, project_id=None, area_id=None, estimate_minutes=None, due_at=None, scheduled_block=None, calendar_event_id=None) -> None`
  - `assign_task_to_project(task_id, project_id) -> None`
  - `assign_task_to_area(task_id, area_id) -> None`
  - `set_recurrence(task_id, mode: str, rule: str) -> None` — UPSERT into `task_recurrence`.
  - `clear_recurrence(task_id) -> None` — DELETE from `task_recurrence`.
  - `clear_task_schedule_link(task_id) -> None` — sets `calendar_event_id=NULL`, `scheduled_block=NULL` for the given task id. **Use this (not `update_task(..., calendar_event_id=None, ...)`) whenever M8-d-b needs to clear the link** — `update_task` treats `None` as "no change" (only non-None kwargs are written), so a sentinel-safe clear method is required. (Fixes B2.)

  **Recurrence engine — `spawn_next_recurrence(completed_task_id) -> dict`:**
  Called ONLY from `complete_task`; idempotent guard: if a task with the same `title` + `project_id` + `area_id` already exists with `status='todo'` AND `created_at > completed_at`, return that existing task (prevents double-spawn on retry).
  - Load the completed task row and its `task_recurrence` row.
  - Compute `next_due_at`:
    - `mode == "fixed"`: parse `rule` as a simple descriptor. Supported rule grammar (document in module docstring): `"every <N> <unit>"` where unit ∈ `days|weeks|months`; `"every <weekday>"` (e.g. `"every monday"`); `"monthly on <N>"` (e.g. `"monthly on 1"`). **Rule-type-specific advance semantics (fixes B4):**
      - `"every <weekday>"` and `"monthly on <N>"`: snap to the next matching calendar boundary strictly after `now` — these are calendar-position rules where a late completion should not shift future instances.
      - `"every <N> days|weeks|months"`: advance from the task's `due_at` field (not `now`) by adding N units repeatedly until the result is strictly after `now`. This preserves the fixed-schedule invariant (late completion does not drift future due dates). If `due_at` is `None`, fall back to `now` as the base. For month arithmetic, clamp the day to the last day of the target month (e.g. `"every 1 months"` from Jan 31 → Feb 28/29 — no `ValueError`).
      Use stdlib `datetime` only. If `rule` is not parseable → `next_due_at = None` (defer; log a warning; do NOT raise — the task is still created).
    - `mode == "after_completion"`: parse `rule` as `"<N> <unit> after completion"` (unit ∈ `days|weeks`). Compute `completed_at + timedelta(N * unit_in_days)` → `next_due_at`.
  - Create a NEW task row with the same `title`, `notes`, `priority`, `tags`, `project_id`, `area_id`, `estimate_minutes`, `due_at=next_due_at`, `status='todo'`; copy the `task_recurrence` row to the new task (so recurrence carries forward).
  - Return the new task dict.

  **Subtasks:**
  - `add_subtask(task_id, title, position=0) -> str`
  - `complete_subtask(subtask_id) -> None`
  - `list_subtasks(task_id) -> list[dict]`
  - `delete_subtask(subtask_id) -> None`

  **Suggestions (capture inbox):**
  - `create_suggestion(title, *, notes=None, source="manual", raw_context=None, commitment_shape=None) -> str` — writes `commitment_shape` column (U7 fix)
  - `list_suggestions(*, status="pending") -> list[dict]`
  - `accept_suggestion(suggestion_id, *, project_id=None, area_id=None, due_at=None) -> str` — sets suggestion `status='accepted'`, creates a task from the suggestion data + overrides, returns the new `task_id`.
  - `reject_suggestion(suggestion_id) -> None`

  **Area contents helper:**
  - `area_contents(area_id) -> dict` — returns `{"area": ..., "projects": [...], "tasks": [...]}` where tasks = tasks directly on the area (no project).

  — done when: `uv run mypy --strict src` passes; repository methods are exercised in Task 5 tests.

### Phase 2 — Store + Tools + Manifest

- [ ] **Task 3: ProductivityStore** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/store.py` —

  `class ProductivityStore` constructed with `(settings: Settings, key_provider: KeyProvider)`.

  `def _db_path(self) -> Path`:
  `paths.scope_dir(settings, OWNER_PRIVATE) / "relational" / "productivity.db"`.

  `def _connect(self)`:
  ```python
  key = key_provider.dek_for_scope(OWNER_PRIVATE)  # raises ScopeLockedError → propagates
  db_path = self._db_path()
  db_path.parent.mkdir(parents=True, exist_ok=True)
  key_hex = key.as_hex()  # local variable only — never assigned to self or module attr
  conn = sqlcipher_open(db_path, key_hex)
  conn.execute("PRAGMA foreign_keys = ON")
  create_schema(conn)
  return conn
  ```
  Off-hardware fallback: if `sqlcipher_open` raises `ImportError` (binding not installed), fall back to `sqlite3.connect(str(db_path))` with a `# FALLBACK: no encryption` comment (mirrors M4-a off-hardware pattern). The fallback is for CI/dev only; the real keyed open is GATED on-hardware (Task 6). Document this fallback inline.

  Lazy-open pattern: `_conn: Connection | None = None` as an instance attribute; `def _get_conn(self)` calls `_connect()` on first access and caches in `_conn`. `close()` closes and clears the handle.

  Expose every `ProductivityRepository` method as a thin delegation:
  ```python
  def create_area(self, title, **kwargs): return ProductivityRepository(self._get_conn()).create_area(title, **kwargs)
  ```
  (One `ProductivityRepository(conn)` per call is fine at productivity scale — no pooling needed; document.)

  — done when: `uv run mypy --strict src` passes; `ProductivityStore(settings, FakeKeyProvider(owner_unlocked=False))` raises `ScopeLockedError` on first data access; `ProductivityStore(settings, FakeKeyProvider(owner_unlocked=True))` round-trips a `create_area` + `get_area` against the fallback sqlite.

- [ ] **Task 4: Tool callables** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` —

  Each tool callable is a plain Python **`async def`** function (ADR-016: every `ToolSpec.callable_ref` is uniformly `async def` returning a Pydantic result model — front-door, read-only, no-I/O alike; the Brain/GATE dispatch sites `await` it) with a Pydantic `BaseModel` args class and a Pydantic `BaseModel` return class. Thin: validate args, call `store.<method>`, return result. The `store.<method>` calls are sync SQLCipher reads/writes — they stay sync inside the `async def` body (no `await` on them); the function is `async def` purely for `callable_ref` signature uniformity (zero-cost — it returns immediately without suspending). All `action_risk = ActionRisk.READ` or `ActionRisk.WRITE` per the tables below; ALL tools are auto (no gating). 30 tools total (12 read + 18 write).

  Define a module-level `_store: ProductivityStore | None = None` and `def init_tools(store: ProductivityStore) -> None` that sets it (the manifest wiring seam — the brain injects the store at startup; tools call `_get_store()` which raises `RuntimeError("productivity store not initialised")` if unset).

  **Read tools** (`action_risk=READ`):

  | Callable name | Args model fields | Return model |
  |---|---|---|
  | `task_list` | `status: str \| None`, `project_id: str \| None`, `area_id: str \| None` | `TaskListResult(tasks: list[dict])` |
  | `task_get` | `id: str` | `TaskResult(task: dict \| None)` |
  | `task_search` | `query: str` | `TaskListResult` |
  | `task_today` | _(no fields)_ | `TaskListResult` |
  | `task_upcoming` | `days: int = 7` | `TaskListResult` |
  | `task_overdue` | _(no fields)_ | `TaskListResult` |
  | `project_list` | `status: str \| None`, `area_id: str \| None` | `ProjectListResult(projects: list[dict])` |
  | `project_get` | `id: str` | `ProjectResult(project: dict \| None)` |
  | `project_tasks` | `id: str` | `TaskListResult` |
  | `area_list` | `include_archived: bool = False` | `AreaListResult(areas: list[dict])` |
  | `area_get` | `id: str` | `AreaResult(area: dict \| None)` |
  | `area_contents` | `id: str` | `AreaContentsResult(area: dict \| None, projects: list[dict], tasks: list[dict])` |

  **Write tools** (`action_risk=WRITE`):

  | Callable name | Args model fields | Return model |
  |---|---|---|
  | `task_create` | `title: str`, `notes: str \| None`, `priority: str = "none"`, `tags: list[str] = []`, `project_id: str \| None`, `area_id: str \| None`, `estimate_minutes: int \| None`, `due_at: str \| None` | `TaskCreatedResult(task_id: str)` |
  | `task_update` | `id: str`, `title: str \| None`, `notes: str \| None`, `priority: str \| None`, `tags: list[str] \| None`, `project_id: str \| None`, `area_id: str \| None`, `estimate_minutes: int \| None`, `due_at: str \| None` | `OkResult(ok: bool = True)` |
  | `task_complete` | `id: str` | `TaskCompleteResult(spawned_task: dict \| None)` (the recurrence-spawned next task, or None) |
  | `task_cancel` | `id: str` | `OkResult` |
  | `task_set_recurrence` | `task_id: str`, `mode: str`, `rule: str` | `OkResult` |
  | `task_assign_to_project` | `task_id: str`, `project_id: str` | `OkResult` |
  | `task_assign_to_area` | `task_id: str`, `area_id: str` | `OkResult` |
  | `project_create` | `title: str`, `notes: str \| None`, `area_id: str \| None`, `target_date: str \| None` | `ProjectCreatedResult(project_id: str)` |
  | `project_update` | `id: str`, `title: str \| None`, `status: str \| None`, `notes: str \| None`, `target_date: str \| None` | `OkResult` |
  | `project_archive` | `id: str` | `OkResult` |
  | `project_assign_to_area` | `project_id: str`, `area_id: str` | `OkResult` |
  | `area_create` | `title: str`, `notes: str \| None` | `AreaCreatedResult(area_id: str)` |
  | `area_update` | `id: str`, `title: str \| None`, `notes: str \| None` | `OkResult` |
  | `area_archive` | `id: str` | `OkResult` |
  | `suggestion_create` | `title: str`, `notes: str \| None`, `source: str = "manual"` | `SuggestionCreatedResult(suggestion_id: str)` |
  | `suggestion_list` | `status: str = "pending"` | `SuggestionListResult(suggestions: list[dict])` |
  | `suggestion_accept` | `suggestion_id: str`, `project_id: str \| None`, `area_id: str \| None`, `due_at: str \| None` | `TaskCreatedResult` |
  | `suggestion_reject` | `suggestion_id: str` | `OkResult` |

  — done when: `uv run mypy --strict src` passes; every callable is importable, is a coroutine function (`inspect.iscoroutinefunction(task_create) is True` — ADR-016), and its args/return classes are valid Pydantic models; `await task_create(...)` with an uninitialised store raises `RuntimeError` (async test — the `RuntimeError` surfaces when the coroutine is awaited).

- [ ] **Task 5: ModuleManifest** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` —

  `def productivity_manifest(store: ProductivityStore) -> ModuleManifest`:
  1. Call `init_tools(store)`.
  2. Build a `ToolSpec` for every callable in Task 4 (30 tools total — 12 read + 18 write). Use the exact `name` strings below (dot-namespaced: `"task.list"`, `"task.get"`, etc. mirroring productivity.md §D naming):

     Read (12): `task.list`, `task.get`, `task.search`, `task.today`, `task.upcoming`, `task.overdue`, `project.list`, `project.get`, `project.tasks`, `area.list`, `area.get`, `area.contents`.
     Write (18): `task.create`, `task.update`, `task.complete`, `task.cancel`, `task.set_recurrence`, `task.assign_to_project`, `task.assign_to_area`, `project.create`, `project.update`, `project.archive`, `project.assign_to_area`, `area.create`, `area.update`, `area.archive`, `suggestion.create`, `suggestion.list`, `suggestion.accept`, `suggestion.reject`.

  3. Return:
     ```python
     ModuleManifest(
         name="productivity",
         version="0.1.0",
         description="Owned tasks, projects, and areas — Artemis is the source of truth.",
         tools=[...],  # all 30 ToolSpecs
         data_scope=DataScope.OWNER_PRIVATE,
         permissions=Permissions(owner=True, guest=False),
         proactive_hooks=[],   # hooks are M8-d-c
         ui=UiSurface(kind="none"),
     )
     ```

  Re-export `productivity_manifest` and `ProductivityStore` from `modules/productivity/__init__.py`.

  — done when: `uv run mypy --strict src` passes; `productivity_manifest(store).name == "productivity"`; `len(productivity_manifest(store).tools) == 30`; all tool names are unique within the manifest (the `ModuleManifest` validator enforces this).

- [ ] **Task 6 (GATED — on-hardware):** Real keyed SQLCipher open of `productivity.db` — on the Mini with the M2-c binding installed and the broker vault mounted + owner unlocked: `ProductivityStore(get_settings(), BrokerKeyProvider(...)).create_area("Health")` succeeds; wrong key fails; `productivity.db` is not plaintext-readable; `PRAGMA foreign_keys = ON` is confirmed active on the keyed connection. — done when: recorded in handoff.

- [ ] **Task 7: Tests** — files: `/Users/artemis-build/artemis/tests/test_productivity_core.py` — typed pytest. Module fixture: `FakeKeyProvider({"owner-private": os.urandom(32)}, owner_unlocked=True)` + `Settings` with `data_root=tmp_path`; attempt the real `sqlcipher_open` — if unavailable, fall back to a plain `sqlite3.connect` (same schema, no key) with encryption-specific assertions skipped.

  - **Schema:** `create_schema` on a fresh connection creates all 7 tables and 6+ indexes (assert via `sqlite_master`); idempotent re-call raises no error.
  - **Area CRUD:** `create_area("Health")` → `get_area(id)` round-trips; `list_areas(include_archived=False)` excludes archived; `archive_area(id)` → excluded from default list; `area_contents(id)` returns correct shape.
  - **Project CRUD:** `create_project("Q3 budget", area_id=area_id)` → `get_project` → FK to area; `list_projects(status="active")` includes it; `project_tasks(id)` returns empty list.
  - **Eager GOAL entity (Decision D3):** `create_project("Build feature", entity_repo=FakeEntityRepository())` → `get_project` returns a row with `project_goal_entity_id == f"goal:{project_id}"`; `FakeEntityRepository.resolve_or_create_entity` was called with `name="Build feature"`, `entity_type=EntityType.GOAL`, `entity_id=f"goal:{project_id}"`. Without `entity_repo` (default None): `project_goal_entity_id` is NULL; no error raised (degrade-don't-crash).
  - **Task CRUD + FK enforcement:** `create_task("Send report", project_id=proj_id, due_at="2026-07-01")` → `get_task` includes it; `today_tasks()` / `overdue_tasks()` / `upcoming_tasks()` return correct rows for manipulated `due_at` values; creating a task with a non-existent `project_id` raises an IntegrityError (FK enforced).
  - **Recurrence — fixed mode:** `create_task` → `set_recurrence(mode="fixed", rule="every monday")`; `complete_task(id)` returns `spawned_task` with `status="todo"` and `due_at` = next Monday ≥ today; the spawned task has its OWN `task_recurrence` row (recurrence carries forward). Calling `complete_task` again on the SAME original task (now done) is idempotent (no second spawn — already done).
  - **Recurrence — after_completion mode:** `set_recurrence(mode="after_completion", rule="7 days after completion")`; `complete_task(id)` → spawned task's `due_at` = `completed_at + 7 days`.
  - **Recurrence idempotency guard (B3 fix):** `complete_task(id)` called a second time on a task already in `status='done'` returns `None` immediately (no-op early-return). The spawn guard inside `spawn_next_recurrence` uses `>=` (not strict `>`) when comparing `created_at >= completed_at` to tolerate same-second timestamps.
  - **Suggestion flow:** `create_suggestion("Call dentist", source="chat")` → `list_suggestions(status="pending")` includes it; `accept_suggestion(id)` creates a task and returns `task_id`; `list_suggestions(status="pending")` is now empty; `reject_suggestion` sets status to rejected.
  - **ScopeLockedError propagation:** `ProductivityStore(settings, FakeKeyProvider(owner_unlocked=False))._get_conn()` raises `ScopeLockedError` (no key → no open).
  - **Manifest shape:** `productivity_manifest(store).name == "productivity"`; `len(tools) == 30`; no duplicate tool names; `data_scope == DataScope.OWNER_PRIVATE`; `proactive_hooks == []`.
  - **Mypy + ruff:** `uv run mypy --strict src tests/test_productivity_core.py` and `uv run ruff check . && uv run ruff format --check .` both exit 0.

  — done when: `uv run pytest -q tests/test_productivity_core.py` passes AND both linters exit 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/__init__.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/productivity/schema.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/productivity/repository.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/productivity/store.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` |
| Create | `/Users/artemis-build/artemis/tests/test_productivity_core.py` |
| Delete | (none) |
| Modify | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_productivity_core.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_productivity_core.py` | Test gate (real keyed or plain-sqlite fallback) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/**`, `tests/test_productivity_core.py` |
| `git commit` | `"feat: M8-d-a productivity core — owned SQLCipher schema, CRUD repository, recurrence engine, all tools, ModuleManifest"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot + data-root resolution (`paths.scope_dir`) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No new PyPI deps; all stdlib + M0/M2 already-present SQLCipher binding |

## Specialist Context

### Security

This store holds owner task/project/area data — OWNER_PRIVATE, Tier-1. Invariants the build MUST honour:

- **Owner-private at rest:** `productivity.db` is opened via M2-c `sqlcipher_open` with the broker-delivered DEK; `ScopeLockedError` propagates without unlocking — no plaintext fallback in production (the CI fallback is explicitly annotated and disabled by a feature flag / binding check).
- **`key.as_hex()` is a local variable inside `_connect()` only** — never assigned to `self`, a module attr, or a log. Matches the `SqlCipherTokenStore._connect` pattern from M8-a (the project-wide standard for this).
- **FK enforcement is ON** (`PRAGMA foreign_keys = ON`) on every connection, including the CI fallback — referential integrity is part of the correctness invariant, not just a nice-to-have.
- **No user-generated content reaches the tools unvalidated** — all args go through Pydantic models; `tags` are a `list[str]` serialised to JSON (not interpolated into SQL); `status`/`priority`/`mode` are validated against the StrEnum constants before any INSERT.
- **`suggestions` created from external sources (email) are inert until `accept_suggestion` is called.** M8-d-a does not build the capture path — that is M8-d-c — but the `source` column and `status='pending'` fence are in place. No LLM-generative action may execute on a suggestion's `raw_context` field in this spec.
- **Recurrence spawn is idempotency-guarded** — the same task cannot be double-spawned on a retry; the guard prevents phantom duplicate tasks from network-retry or test reruns.
- No dep additions → no `pip-audit` gate needed; if any dep is added during build, run `uv run pip-audit` (supply-chain gate from M8-a precedent).

[apex-security review note: the FK-enforced schema + parameterised SQL + Pydantic validation cover the injection surface; the owner-private SQLCipher boundary is the same pattern proven at M2-c/M4-a/M8-a. The `suggestions.raw_context` field must be treated as untrusted if email-sourced — enforced in M8-d-c; document here as a standing FLAG for that spec.]

### Performance

Productivity scale is hundreds–low thousands of tasks. No LanceDB, no vector index, no FTS5 — plain parameterised SQL is the right tool. The partial index on `tasks(due_at) WHERE status NOT IN ('done','cancelled')` keeps `today_tasks`/`overdue_tasks` index-driven. `search_tasks` is a LIKE scan — acceptable at this scale; a full-text upgrade is deferred. One `ProductivityRepository(conn)` per store method call is negligible overhead at this scale; a connection pool would be premature.

### Accessibility

(none — no frontend in M8-d-a)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/productivity/*.py` | Type + docstring all public exports; document the recurrence rule grammar, the `key.as_hex()` local-only invariant, the FK-on constraint, and the off-hardware fallback |
| Data model | `docs/technical/architecture/data-model.md` | Add the Productivity entities (areas / projects / tasks / subtasks / task_recurrence / suggestions) — reconcile at spec execution |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_productivity_core.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_productivity_core.py` → verify: schema idempotency, area/project/task CRUD, FK integrity error on bad FK, `today/overdue/upcoming` filters, recurrence-fixed spawns with correct next Monday, recurrence-after-completion spawns `completed_at + 7d`, recurrence idempotency guard (no double-spawn), suggestion accept/reject flow, `ScopeLockedError` on locked provider, manifest has 30 unique tools + `proactive_hooks == []` — all pass.
- [ ] `uv run python -c "from artemis.modules.productivity import productivity_manifest, ProductivityStore; print('ok')"` → verify: prints `ok` (import smoke).
- [ ] `uv run python -c "from artemis.modules.productivity.manifest import productivity_manifest; from artemis.manifest import DataScope; ..."` (inline assert `data_scope == DataScope.OWNER_PRIVATE` and `len(tools) == 30`) → verify: passes.
- [ ] (GATED, on Mini) `ProductivityStore` opens `productivity.db` under the broker-mounted vault; wrong key fails; FK enforcement active on the keyed connection; `create_area("Health")` + `get_area` round-trips on the real keyed DB → verify: recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

- [x] Task 1: Schema DDL (7 tables, indexes, StrEnum constants, idempotent create_schema)
- [x] Task 2: Repository (areas/projects/tasks/subtasks/suggestions CRUD + recurrence engine)
- [x] Task 3: ProductivityStore (lazy keyed _connect via sqlcipher_open seam, thin delegation)
- [x] Task 4: Tool callables (30 async ToolSpec callables, init_tools store-injection seam)
- [x] Task 5: ModuleManifest (productivity_manifest → 30 tools, OWNER_PRIVATE, no hooks)
- [ ] Task 6: GATED on-hardware (real keyed SQLCipher open) — skipped, needs the Mini
- [x] Task 7: Tests (tests/test_productivity_core.py, +11 tests)

**Built by Codex (gpt-5.5) via `codex exec`. Independently verified green: ruff format+check clean, mypy clean (88 src files), pytest 227 passed (+11 from 216 baseline).**

**Deviations from spec (pre-approved reality-adaptations):**
1. Stale `/Users/artemis-build/artemis/` path prefixes → repo-relative (cwd).
2. `_connect()` mirrors `PendingActionStore._connect`; the spec's `try/except ImportError` off-hardware fallback was dropped as unreachable — `sqlcipher_open` is itself the dev-stub seam (plain sqlite3 off-hardware, never raises ImportError). `PRAGMA foreign_keys = ON` placed at the top of `create_schema` (so direct-repo tests get FK enforcement) and kept in `_connect`.
3. **Entity GOAL interface fiction:** the live `EntityRepository.resolve_or_create_entity(name, entity_type, *, external_ref=None) -> str` has no `entity_id` kwarg and returns `str` (not `EntityRef`). Real wiring is M4-d (deferred); this spec only ever passes a fake. Adapted: `create_project`'s `entity_repo` is typed against a narrow `GoalEntityRepo` Protocol defined in `repository.py` (`resolve_or_create_entity(*, name, entity_type, entity_id) -> EntityRef`), not the concrete class. Test supplies a `FakeEntityRepository`. Flag for M4-d: the real eager-GOAL wiring must reconcile this signature gap.
4. `now_iso()` defined locally (timezone-aware) rather than importing memory's — avoids cross-module coupling.
5. Doc-table task (data-model.md) left untouched — out of Files-to-Change scope.
