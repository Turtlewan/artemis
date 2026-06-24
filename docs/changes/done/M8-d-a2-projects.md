---
spec: m8-d-a2-projects
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave F0 · NEW (split from M8-d-a). Implements the LOCKED productivity spoke split:
     Projects becomes its own module surface (separate Planning-cluster card per the UI lock) while
     Tasks keeps task/subtask/recurrence/suggestions. The post-areas-drop 22 tools split across two
     module manifests. GOAL-entity eager-create (D3) lives with Projects. Prereq: M8-d-a-areas-drop. -->

# Spec: M8-d-a2-projects — split Projects into its own module surface (separate manifest + card)

**Identity:** Carve the Projects domain out of the single `productivity` module into a sibling `projects` surface — a separate `ModuleManifest` (`name="projects"`) over the SAME owned SQLCipher store (one DB, two manifests), so Projects gets its own glance card in the Planning cluster while Tasks keeps task/subtask/recurrence/suggestions. GOAL-entity eager-create (Decision D3) moves with Projects.
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (Tasks module + Projects module split) · docs/findings/cluster-spec-roadmap.md Wave F0.

## Assumptions

- **M8-d-a-areas-drop** complete: the productivity module has 6 tables (no `areas`), 22 tools, and the `ProductivityRepository` has project + task method groups with no `area_id`. `create_project(title, *, notes, target_date, entity_repo)` does the eager GOAL-entity create (D3 preserved). → impact: Stop (this spec re-partitions the post-areas-drop tool set; it must run after areas-drop, not before).
- The split is **manifest-level, not store-level** — both modules share ONE `productivity.db` and ONE `ProductivityRepository`/`ProductivityStore`. Projects and Tasks are not separate scopes; they are separate *tool surfaces / cards* over the same owned store. A cross-module DB join is never needed (they're the same DB), and no `EntityRef` indirection is required between them (project↔task linkage is the existing `tasks.project_id` FK). → impact: Stop (this is a UI/manifest carve, NOT a data re-architecture; do not create a second SQLCipher DB).
- The `tasks.project_id TEXT REFERENCES projects(id)` FK is the project↔task linkage — unchanged. `project.tasks` (list a project's tasks) stays a Projects-surface read tool. → impact: Stop.
- **M4-d-1** GOAL-entity backbone unchanged; `create_project`'s eager `resolve_or_create_entity(EntityType.GOAL, ...)` moves to the Projects manifest's tool surface but calls the same repository method. → impact: Low.
- **M1-a** `ModuleManifest`/`ToolSpec` unchanged; two manifests can register on one `ToolRegistry` as long as their `(manifest.name, tool.name)` fq ids are unique — they are (`projects.create` vs `task.create`). → impact: Stop (the registry keys on fq id; `name="projects"` namespaces the project tools).
- Downstream specs that reference productivity tools by fq id keep working: `task.schedule` (M8-d-b), `task.complete`, `suggestion.accept` stay on the **tasks** manifest; `project.complete` (M8-d-c2) stays on the **projects** manifest. The capture/hooks specs import `ProductivityStore` (the shared store) not a specific manifest, so they are unaffected. → impact: Caution (verify the M8-d-b `task.schedule` wiring and the M8-d-c2 `project.complete` wiring land on the correct manifest — documented in § Tool partition).
- Off-hardware: same plain-sqlite fallback; tests assert two manifests, disjoint tool sets, shared store. → impact: Low.

Simplicity check: considered splitting the store too (separate `projects.db`) — rejected; project↔task linkage is a single FK in one DB, a store split would force an `EntityRef`/ToolRegistry indirection for what is a local join, adding cost for zero benefit. The minimal split is two `ModuleManifest`s over one store. No new repository, no new schema, no data move.

## Prerequisites

- Specs complete: **M8-d-a-areas-drop** (the 22-tool post-areas-drop baseline). **M4-d-1** (GOAL entity).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` | modify | split into `tasks_manifest(store, ...)` (keeps task/subtask/recurrence/suggestion tools + hooks) and a new `projects_manifest(store)` factory; or keep one file exporting both factories |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` | modify | re-export both `tasks_manifest` and `projects_manifest`; keep `productivity_manifest` as a thin deprecated alias for `tasks_manifest` (back-compat for M8-d-b/c1/c2 wiring during their re-spec) OR update all call sites — see § Migration note |
| `/Users/artemis-build/artemis/tests/test_projects_module.py` | create | two-manifest shape, disjoint tool sets, project CRUD via the projects surface, shared-store round-trip (task created on tasks surface visible to `project.tasks` on projects surface) |
| `/Users/artemis-build/artemis/tests/test_productivity_core.py` | modify | update the manifest-shape assertions to the two-manifest split (tasks 17 / projects 5) |

All paths under `/Users/artemis-build/artemis/`.

## Tool partition (post-areas-drop 22 tools → two manifests)

**Projects manifest** (`name="projects"`, ~5 tools): `project.create`, `project.get`, `project.list`, `project.update`, `project.archive`, `project.tasks`. (`project.complete` is added later by M8-d-c2 → lands here, → 6 with c2.) — these are the project-surface tools.

**Tasks manifest** (`name="tasks"` — renamed from `productivity` for card clarity, OR keep `name="productivity"` — see § Naming decision; remaining ~16 tools): all `task.*` (create/get/list/search/today/upcoming/overdue/update/complete/cancel/set_recurrence/assign_to_project) + all `suggestion.*` (create/list/accept/reject). The Tier-1 hooks (M8-d-c1) ride the tasks manifest. `task.schedule` (M8-d-b) lands here.

(Subtask tools, if exposed as tools in M8-d-a, ride the tasks manifest; if they were repository-only helpers, no tool to partition.)

## Tasks

- [ ] **Task 1: Split the manifest factory** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` (modify) —

  Replace the single `productivity_manifest(store, ...)` with two factories in the same file:

  ```python
  def projects_manifest(store: ProductivityStore) -> ModuleManifest:
      init_project_tools(store)   # or reuse the shared init_tools if tools.py stays one module
      return ModuleManifest(
          name="projects",
          version="0.1.0",
          description="Owned projects — goals with linked tasks. Artemis is the source of truth.",
          tools=[<the 5 project ToolSpecs>],   # project.create/get/list/update/archive/tasks
          data_scope=DataScope.OWNER_PRIVATE,
          permissions=Permissions(owner=True, guest=False),
          proactive_hooks=[],                  # project hooks (weekly-review) ride the tasks manifest in c1; none here
          ui=UiSurface(kind="card"),           # separate Planning-cluster card (UI lock)
      )

  def tasks_manifest(store: ProductivityStore, schedule_fn=..., write_tools=..., registry=...) -> ModuleManifest:
      # the post-M8-d-b/c1 signature (schedule_fn/write_tools/registry) stays on THIS manifest
      init_tools(store); init_schedule_fn(schedule_fn); ...; register_productivity_templates(registry)
      return ModuleManifest(
          name="tasks",
          version="0.1.0",
          description="Owned tasks — capture, schedule, recurrence. Artemis is the source of truth.",
          tools=[<the 16 task + suggestion ToolSpecs>],
          data_scope=DataScope.OWNER_PRIVATE,
          permissions=Permissions(owner=True, guest=False),
          proactive_hooks=build_productivity_hooks(store),   # M8-d-c1 hooks ride here
          ui=UiSurface(kind="card"),
      )
  ```

  **UiSurface note:** if M8-d-a set `ui=UiSurface(kind="none")`, this spec sets `kind="card"` for both (each gets a Planning-cluster glance card per the UI lock). Confirm the `UiSurface` API against M1-a; if `kind="card"` is not yet a valid value, keep `kind="none"` and FLAG that the card surface is declared in Wave U (CLIENT) instead — the manifest split is the load-bearing change, the UI-kind is cosmetic. (Resolve by reading M1-a `UiSurface`; default to the existing value if uncertain — do not invent a kind.)

  — done when: `uv run mypy --strict src` passes; `projects_manifest(store).name == "projects"` with the 5 project tools; `tasks_manifest(store, ...).name in {"tasks","productivity"}` with the 16 task/suggestion tools + 3 hooks; the two tool-name sets are disjoint; both register on one `ToolRegistry` without an fq-id collision.

- [ ] **Task 2: Naming + back-compat re-exports** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` (modify) —

  **§ Naming decision:** the bare-tool names stay dot-namespaced by manifest: `task.*` on the tasks manifest, `project.*` on the projects manifest (the registry fq id is `{manifest.name}.{tool.name}`, so a tool named `"task.create"` on a manifest named `"tasks"` would yield `tasks.task.create` — WRONG). **Resolve:** bare tool names are the LAST segment only (`name="create"`, not `name="task.create"`), and the manifest name supplies the namespace. So `tasks_manifest` tool `name="create"` → fq id `tasks.create`; `projects_manifest` tool `name="create"` → fq id `projects.create`. This is the contracts.md Seam 2 convention (`ToolSpec.name` is bare; `module.tool` is the registry id). **If M8-d-a used full dotted names** (`name="task.create"`), this spec normalises them to bare last-segment names + relies on the manifest name for the namespace — update any downstream fq-id references (`task.schedule` stays the fq id because the tasks manifest is named `tasks` and the tool is named `schedule`). Document the exact fq-id map in the spec output.

  Re-export `tasks_manifest` and `projects_manifest`. Keep `productivity_manifest = tasks_manifest` as a deprecated alias so M8-d-b/c1/c2 wiring (which calls `productivity_manifest`) keeps importing until those specs' F1 re-specs update the call site. Document the alias as transitional.

  — done when: `uv run mypy --strict src` passes; `from artemis.modules.productivity import tasks_manifest, projects_manifest` succeeds; `productivity_manifest is tasks_manifest` (alias); the fq-id map is documented (e.g. `projects.create`, `tasks.create`, `tasks.schedule`).

- [ ] **Task 3: Tests** — files: `/Users/artemis-build/artemis/tests/test_projects_module.py` (create), `/Users/artemis-build/artemis/tests/test_productivity_core.py` (modify) —

  **test_projects_module.py** (new):
  - `projects_manifest(store)` has the 5 project tools; `name == "projects"`; `data_scope == OWNER_PRIVATE`.
  - `tasks_manifest(store, ...)` tool set and the projects tool set are disjoint (no shared bare-name+manifest fq id collision when both register on one `ToolRegistry`).
  - **Shared-store round-trip:** create a task with `project_id=pid` via the tasks surface tools; `project.tasks(pid)` on the projects surface returns it — proving one store, two surfaces.
  - **Eager GOAL preserved:** `project.create` via the projects surface with a `FakeEntityRepository` → `project_goal_entity_id == f"goal:{project_id}"` (D3).
  - Both manifests register on one `ToolRegistry(FakeEmbedder())` without raising (fq ids unique).

  **test_productivity_core.py** (modify): update the manifest-shape test from `len(tools) == 22` (single) to two manifests summing to 22 (e.g. projects 5 + tasks 17 — exact split per the partition).

  — done when: `uv run pytest -q tests/test_projects_module.py tests/test_productivity_core.py` passes AND `uv run mypy --strict src tests/test_projects_module.py` passes.

## Migration note (for the F1 re-specs)

M8-d-b/c1/c2 currently call `productivity_manifest(store, ...)`. The deprecated alias keeps them green during this F0 build. The F1 re-specs (M8-d-b focus-slot, M8-d-c1 wake-digest) update their call sites to `tasks_manifest(...)` and confirm `task.schedule`/hooks land on the tasks manifest; the M8-d-c2 capture amendment confirms `project.complete` lands on the `projects_manifest`. This spec only provides the split + alias; the call-site updates are in those specs' Files to Change.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` |
| Create | `/Users/artemis-build/artemis/tests/test_projects_module.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_productivity_core.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_projects_module.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_projects_module.py tests/test_productivity_core.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/productivity/{manifest,__init__}.py`, `tests/test_projects_module.py`, `tests/test_productivity_core.py` |
| `git commit` | `"refactor: split Projects into its own module manifest (tasks_manifest + projects_manifest over one store)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure manifest re-partition |

## Specialist Context

### Security

- Both manifests are `OWNER_PRIVATE` — no security posture change; the split is a tool-surface partition over the same owner-gated SQLCipher store. The GOAL-entity eager-create (D3) is preserved on the projects surface. No new external-effect tools (all WRITE/READ AUTO, self-only per ADR-011). [apex-security note: confirm the two manifests cannot widen scope — both stay `OWNER_PRIVATE`, `Permissions(owner=True, guest=False)`; guest mode sees neither.]

### Performance

- Two manifests, one store, one connection-per-call pattern (M8-d-a) — no perf change. Registry holds a few more fq-id entries — negligible.

### Accessibility

(none — no frontend here; the two cards are Wave U / CLIENT)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/productivity/manifest.py` | Document the two-manifest-one-store split, the fq-id map, and that project↔task linkage is the `tasks.project_id` FK (no EntityRef indirection between them) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_projects_module.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_projects_module.py tests/test_productivity_core.py` → verify: two manifests with disjoint tool sets; shared-store round-trip (task on tasks surface visible via `project.tasks`); eager GOAL preserved; both register on one ToolRegistry without fq-id collision; tasks+projects tool counts sum to 22.
- [ ] `uv run python -c "from artemis.modules.productivity import tasks_manifest, projects_manifest, ProductivityStore; print('ok')"` → verify: prints `ok`.

## Progress
_(Coding mode writes here — do not edit manually)_
