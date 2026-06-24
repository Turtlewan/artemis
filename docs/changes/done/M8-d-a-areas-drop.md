---
spec: m8-d-a-areas-drop
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave F0 · AMENDS M8-d-a + sweeps M8-d-c1/M8-d-c2. Implements the LOCKED structural change:
     DROP the `areas` table + `area_id` FK entirely. Two levels only: Projects→Tasks; standalone
     tasks float. T8 "archived-area" decision is moot. This is the data-migration / schema-shape change
     half of the productivity spoke split; the Projects-module carve-out is M8-d-a2-projects.
     cross_model_review: true (schema/data-migration change on an owned SQLCipher store). -->

# Spec: M8-d-a-areas-drop — remove the `areas` table + `area_id` FK from the Productivity core

**Identity:** Surgical removal of the Areas life-domain layer from M8-d-a's schema, repository, and tool surface — and the matching grep-sweep of every `area`/`area_id` reference across M8-d-c1 and M8-d-c2. After this: two levels only — Projects own Tasks; tasks without a project float. The 30-tool count drops to 22 (8 area-related tools removed — see Task 3, which lists all 8); the Projects-module split (M8-d-a2) re-partitions the remainder.
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (Areas DROPPED, structural) · docs/findings/cluster-spec-roadmap.md Wave F0 / Risk R1.

## Assumptions

- **M8-d-a** is the spec being amended: `src/artemis/modules/productivity/{schema.py,repository.py,tools.py,manifest.py,__init__.py}` exist with the 7-table schema (`areas`/`projects`/`tasks`/`task_subtasks`/`task_recurrence`/`suggestions`/`meta`), the `ProductivityRepository` area/project/task method groups, and the 30-tool `ModuleManifest`. This spec EDITS those files. If M8-d-a has not yet been built, this amendment's deltas fold into the M8-d-a build directly (the coder applies the post-areas-drop schema from the start — there is no live owner data to migrate on the dev box; the `areas` table is simply never created). → impact: Stop (this is a *pre-build* schema correction, not a live-data migration — the dev box has no productivity data yet; on-hardware the migration tail in Task 5 applies only if data already exists).
- **M4-d-1** entity backbone (`EntityRepository`, `EntityType.GOAL`, `EntityRef`) is unchanged — the eager-GOAL-on-create-project path (Decision D3, contracts.md Seam 6) is **preserved**; only Areas are removed. → impact: Stop (do NOT touch the `project_goal_entity_id` column or the GOAL-entity creation in `create_project`).
- The `tasks` table's `project_id TEXT REFERENCES projects(id)` FK is **kept** (Projects→Tasks is the surviving one level of hierarchy). Only `tasks.area_id` and `projects.area_id` columns + the `areas` table are removed. → impact: Stop.
- This amendment does NOT split Projects into its own module — that is **M8-d-a2-projects** (the second F0 spec). This spec leaves Projects and Tasks in the single `productivity` module; M8-d-a2 carves Projects out afterward. The two are sequenced: areas-drop first (schema correct), then the module split (file partition). → impact: Caution (keep this spec schema/tool-removal-only; do not pre-empt the module split).
- Off-hardware: plain-sqlite fallback, `FakeKeyProvider(owner_unlocked=True)` — same harness as M8-d-a Task 7. → impact: Low.

Simplicity check: the minimum change is (a) delete the `areas` DDL + both `area_id` columns + their indexes, (b) delete the 5 area repository methods + `area_id` kwargs from project/task methods, (c) delete the 3 area tools + `area_id` args from task/project tool models, (d) fix the 2 downstream specs that read `list_areas`/`area_id`. No new abstractions; this is pure subtraction + a payload-key rename in one hook.

## Prerequisites

- Specs complete: **M8-d-a** (the spec amended — or this folds into its build). **M4-d-1** (GOAL entity, preserved).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/schema.py` | modify | drop `areas` table + DDL; drop `tasks.area_id` + `projects.area_id` columns + their indexes; bump `SCHEMA_VERSION` to `"2"` |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/repository.py` | modify | drop the 5 area methods + `area_id` kwargs from project/task methods + `assign_*_to_area` + `area_contents`; `create_project`/`create_task`/`update_*`/`list_*` lose their `area_id` param |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` | modify | drop `area_create`/`area_update`/`area_archive`/`area_list`/`area_get`/`area_contents`/`task_assign_to_area`/`project_assign_to_area` callables + the `area_id` field from `TaskCreateArgs`/`TaskUpdateArgs`/`ProjectCreateArgs` |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` | modify | drop the area ToolSpecs; tool count 30 → 27 |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` | modify | drop any area re-exports |
| `/Users/artemis-build/artemis/tests/test_productivity_core.py` | modify | drop all area CRUD tests; drop `area_id` assertions in project/task tests; assert `areas` table is absent; assert tool count 27 |
| `/Users/artemis-build/artemis/docs/changes/M8-d-c1-hooks.md` | modify | (spec-doc sweep) drop `list_areas()` call + `area_count` payload key from `make_weekly_review_check` — handled in the F1 re-spec; cross-ref only |
| `/Users/artemis-build/artemis/docs/changes/M8-d-c2-capture-integration.md` | modify | (spec-doc sweep) drop `area_id` kwarg from `accept_with_graduation` + `_push_knowledge` — handled in the F1/capture amendment; cross-ref only |

All source paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Drop Areas from the schema** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/schema.py` (modify) —

  - Remove the entire `areas` `CREATE TABLE` statement + `idx_areas_archived` index.
  - Remove `area_id TEXT REFERENCES areas(id)` from the `projects` DDL; remove `idx_projects_area_id`.
  - Remove `area_id TEXT REFERENCES areas(id)` from the `tasks` DDL; remove `idx_tasks_area_id`.
  - Keep `projects.project_goal_entity_id`, `tasks.project_id` + `idx_tasks_project_id`, and all other columns/indexes.
  - Bump `SCHEMA_VERSION = "2"`. (The `meta` schema_version row reflects the post-areas-drop shape.)
  - `create_schema` now creates **6 tables** (`projects`/`tasks`/`task_subtasks`/`task_recurrence`/`suggestions`/`meta`).

  — done when: `uv run mypy --strict src` passes; `create_schema` on a fresh connection creates 6 tables (no `areas` in `sqlite_master`); `projects` and `tasks` have no `area_id` column (verify via `PRAGMA table_info`); `idx_projects_area_id`/`idx_tasks_area_id`/`idx_areas_archived` are absent.

- [ ] **Task 2: Drop Areas from the repository** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/repository.py` (modify) —

  Remove these methods entirely: `create_area`, `get_area`, `list_areas`, `update_area`, `archive_area`, `assign_project_to_area`, `assign_task_to_area`, `area_contents`.

  Edit the surviving signatures (drop the `area_id` parameter and any `area_id` write/filter):
  - `create_project(title, *, notes=None, target_date=None, entity_repo=None) -> str` (drop `area_id`; GOAL-entity creation preserved).
  - `list_projects(*, status=None, include_archived=False) -> list[dict]` (drop `area_id` filter).
  - `update_project(id, *, title=None, notes=None, status=None, target_date=None) -> None` (drop `area_id`).
  - `create_task(title, *, notes=None, status="todo", priority="none", tags=None, project_id=None, estimate_minutes=None, due_at=None) -> str` (drop `area_id`).
  - `list_tasks(*, status=None, project_id=None) -> list[dict]` (drop `area_id` filter).
  - `update_task(id, *, title=None, notes=None, priority=None, tags=None, project_id=None, estimate_minutes=None, due_at=None, scheduled_block=None, calendar_event_id=None) -> None` (drop `area_id`).
  - `today_tasks`/`overdue_tasks`/`upcoming_tasks`/`search_tasks` — unchanged (never used `area_id`).
  - `spawn_next_recurrence` — drop `area_id` from the idempotency-guard match key and from the copied-task field set (match on `title` + `project_id` only now).

  — done when: `uv run mypy --strict src` passes; the 8 area methods are gone (`hasattr(repo, "create_area") is False`); `create_project("p")` + `create_task("t", project_id=pid)` round-trip with no `area_id` anywhere; `spawn_next_recurrence` idempotency guard uses `title`+`project_id`.

- [ ] **Task 3: Drop Areas from the tools + manifest** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py`, `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py`, `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` (modify) —

  **tools.py:** Remove callables `area_create`, `area_update`, `area_archive`, `area_list`, `area_get`, `area_contents`, `task_assign_to_area`, `project_assign_to_area`. Remove the `area_id` field from `TaskCreateArgs`, `TaskUpdateArgs`, `ProjectCreateArgs`, and the `area_id` kwarg from `suggestion_accept`'s args/call (suggestion accept no longer takes `area_id`). Remove the `AreaCreatedResult`/`AreaListResult`/`AreaResult`/`AreaContentsResult` models.

  **manifest.py:** Remove the corresponding ToolSpecs: `area.create`, `area.update`, `area.archive`, `area.list`, `area.get`, `area.contents`, `task.assign_to_area`, `project.assign_to_area`. **New count: 30 − 8 = 22 tools** in the bare M8-d-a manifest. (Note: M8-d-b adds `task.schedule` → 23; M8-d-c2 adds `project.complete` → 24. The "31"/"32" cumulative counts in the frozen M8-d-b/c1/c2 specs are pre-areas-drop and are re-baselined by this amendment + the F1 re-specs — see § Downstream count re-baseline.)

  **__init__.py:** Drop any area symbol re-exports.

  — done when: `uv run mypy --strict src` passes; the 8 area tools are absent from `productivity_manifest(store).tools`; `len(tools) == 22`; no `area_id` field on any args model (`"area_id" not in TaskCreateArgs.model_fields`).

- [ ] **Task 4: Update the core tests** — files: `/Users/artemis-build/artemis/tests/test_productivity_core.py` (modify) —

  - Delete the "Area CRUD" and `area_contents` test blocks entirely.
  - Delete the eager-GOAL test's `area_id` usage (keep the GOAL-entity assertion — D3 preserved).
  - In the Project/Task CRUD tests: drop `area_id=` args; assert `create_task("t", project_id=pid)` works and that passing `area_id=` is a `TypeError` (the param is gone).
  - Add: `create_schema` creates exactly 6 tables and no `areas` table; `PRAGMA table_info(tasks)` has no `area_id`.
  - Update the manifest-shape test: `len(tools) == 22`; the 8 area tool names are absent; `proactive_hooks == []` unchanged.

  — done when: `uv run pytest -q tests/test_productivity_core.py` passes AND `uv run mypy --strict src tests/test_productivity_core.py` passes.

- [ ] **Task 5 (GATED — on-hardware, conditional):** Live-data migration tail. ONLY if a `productivity.db` with existing data is present on the Mini at build time: write a one-shot migration that (a) snapshots any `area_id` values into a `migrated_area_label` note on affected tasks/projects (so the owner doesn't silently lose the grouping), (b) drops the `areas` table + `area_id` columns via SQLite `ALTER TABLE ... DROP COLUMN` (SQLite ≥3.35) or a table-rebuild, (c) sets `schema_version=2`. On the dev box (no prior data) this is a no-op — the schema is created post-drop from scratch. — done when: recorded in handoff (or marked N/A if no prior data).

## Downstream count re-baseline (spec-doc sweep — applied in the F1 re-specs, recorded here)

The frozen tool-count assertions in M8-d-b / M8-d-c1 / M8-d-c2 were written pre-areas-drop (30 base). After this amendment the base is **22**. The F1 re-specs (M8-d-b focus-slot, M8-d-c1 wake-digest) and the capture amendment carry the corrected counts:
- M8-d-a (post-areas-drop): **22**
- + M8-d-b `task.schedule`: **23**
- + M8-d-c2 `project.complete`: **24**
- The Projects-module split (M8-d-a2) re-partitions these 22 across two modules (≈ Tasks 17 / Projects 5) — see M8-d-a2-projects for the exact partition.

**M8-d-c1 sweep (folded into the F1 wake-digest re-spec):** `make_weekly_review_check` drops `store.list_areas()` (call removed) and the `"area_count"` payload key. The weekly-review payload becomes `{"project_count", "overdue_count", "project_ids"}`.

**M8-d-c2 sweep (folded into the capture amendment):** `accept_with_graduation(self, suggestion_id, *, project_id=None, due_at=None)` drops the `area_id` param; `store.accept_suggestion(...)` is called without `area_id`; `_push_knowledge` drops any `area` reference.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/schema.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/repository.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_productivity_core.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_productivity_core.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_productivity_core.py` | Test gate |
| `uv run grep -rn "area_id\|create_area\|list_areas\|area_contents" src/artemis/modules/productivity/` | Sweep gate — must return zero hits |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/productivity/{schema,repository,tools,manifest,__init__}.py`, `tests/test_productivity_core.py` |
| `git commit` | `"refactor: M8-d-a drop Areas layer — two-level Projects→Tasks; remove areas table + area_id FK"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure schema/code subtraction |

## Specialist Context

### Security

- Removing a table + columns reduces attack surface; no new surface added. The GOAL-entity creation (D3) and `project_goal_entity_id` column are explicitly preserved — do not remove cross-module linkability.
- The on-hardware migration (Task 5) must NOT silently drop owner grouping data — it snapshots `area_id` to a label note before dropping (data-preservation invariant). On the dev box there is no prior data so this is moot; the cross_model_review flag covers the live-migration path on the Mini.
- `SCHEMA_VERSION` bump to `"2"` is the migration trigger; the `meta` row drives whether Task 5's migration runs.

[apex-data review: confirm the FK drop order — drop dependent indexes/columns before the `areas` table; SQLite `DROP COLUMN` requires no FK dependents remain. The table-rebuild path (recreate `tasks`/`projects` without `area_id`, copy rows, swap) is the safe cross-version approach if `DROP COLUMN` is unavailable.]

### Performance

- Fewer columns + fewer indexes = marginally faster writes; no perf concern. The dropped `area_id` indexes were never on the hot path (`today`/`overdue` use the `due_at` partial index, kept).

### Accessibility

(none — no frontend)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/productivity/schema.py` | Document the two-level model (Projects→Tasks; standalone tasks float); note Areas removed at SCHEMA_VERSION 2 |
| Data model | `docs/technical/architecture/data-model.md` | Remove the Areas entity; update the Productivity entity list to 6 tables |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_productivity_core.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_productivity_core.py` → verify: 6 tables created (no `areas`); no `area_id` column on tasks/projects; project/task CRUD round-trips without `area_id`; GOAL-entity eager-create preserved; manifest has 22 unique tools with the 8 area tools absent.
- [ ] `grep -rn "area_id\|create_area\|list_areas\|area_contents\|assign_to_area" src/artemis/modules/productivity/` → verify: zero hits.
- [ ] `uv run python -c "from artemis.modules.productivity import productivity_manifest, ProductivityStore; m=productivity_manifest; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini, conditional) live-data migration preserves area grouping as a label note + sets schema_version=2 → recorded in handoff (or N/A).

## Progress
_(Coding mode writes here — do not edit manually)_
