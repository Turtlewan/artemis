---
spec: m8-d-b-focus-slot-pick
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave F1 · AMENDS M8-d-b (time-blocking seam). Two LOCKED changes:
     (1) X2/T3 — schedule_task biases slot-pick to preferred_focus_window (earliest-within-window,
         else earliest overall) instead of bare slots[0].
     (2) F0 Areas-drop ripple — no area_id anywhere; productivity manifest call site renamed
         productivity_manifest → tasks_manifest; tool count re-baselined 22 + task.schedule = 23.
     Amendment file — do NOT edit the frozen M8-d-b-time-blocking-seam.md. -->

# Spec: M8-d-b-focus-slot-pick — focus-window slot-pick for `schedule_task` + Areas-drop sweep

**Identity:** `schedule_task` (the `calendar.schedule_task` primitive) ranks `find_time` slots by `CalPrefs.preferred_focus_window` via the CAL-prefs `rank_slots_by_focus_window` helper (earliest-within-window, else earliest overall) before picking, replacing the bare `slots[0]`; plus the F0 Areas-drop sweep (no `area_id`; `productivity_manifest` → `tasks_manifest`; tool count 22 + `task.schedule` = 23).
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (X2/T3 LOCKED; Areas DROPPED) · docs/findings/cluster-spec-roadmap.md Wave F1.

## Assumptions

- **M8-d-b** (the frozen `M8-d-b-time-blocking-seam.md`) is built: `src/artemis/modules/calendar/schedule_task.py` defines `schedule_task(args, *, write_tools, find_time_fn, prefs)` (`async def`, ADR-016) which currently picks `slot = result.slots[0]` (the earliest); `ScheduleTaskArgs`/`ScheduledBlock`/`ScheduleTaskResult` are defined; `src/artemis/modules/productivity/tools.py` defines `task_schedule`/`task_complete` callables; the productivity manifest wires `task.schedule`. → impact: Stop (this amendment surgically changes the slot-pick line + the manifest call site; symbol names must match the frozen spec exactly).
- **F1 CAL-prefs amendment** (`CAL-prefs-workingdays-focuswindow.md`) is built FIRST: `CalPrefs` gains `preferred_focus_window: tuple[str, str]` (default `("09:00","12:00")` from `RuntimeConfig.calendar.preferred_focus_window`) and a module-level helper `rank_slots_by_focus_window(slots, focus_window, tz) -> list[FreeSlot]` (or equivalent ranking function) that returns the slots reordered: every slot whose start falls within `[focus_window.start, focus_window.end)` first (preserving their chronological order), then the remaining slots in chronological order. → impact: Stop (this spec REUSES that helper; it does NOT re-implement focus-window logic. If the helper's exact name/signature differs in the CAL-prefs amendment as built, bind to the actual name — confirm before executing; the contract is "a function that ranks slots earliest-within-focus-window-first, else earliest-overall").
- **F0 M8-d-a-areas-drop** is built: the productivity store/repository/tools have NO `area_id`. `update_task(...)` has no `area_id` kwarg. → impact: Stop (the `task_schedule` link-write path calls `update_task` with `calendar_event_id`/`scheduled_block` only — no `area_id`).
- **F0 M8-d-a2-projects** is built: the manifest factory is `tasks_manifest(store, schedule_fn, write_tools, registry)` (the `task.*`/`suggestion.*` surface; `task.schedule` lands here). `productivity_manifest` survives only as a deprecated alias for `tasks_manifest`. → impact: Stop (this spec updates the `task.schedule` wiring call site to `tasks_manifest` and asserts `task.schedule`'s fq id is `tasks.schedule`).
- **CAL-a** `FindTimeResult.slots: list[FreeSlot]` where `FreeSlot` has `start_dt: str`, `end_dt: str` (ISO-8601). The focus-window check parses `FreeSlot.start_dt`'s time-of-day and tests membership in the `preferred_focus_window` HH:MM band. → impact: Caution (the ranking helper, owned by CAL-prefs, does the parse; this spec only feeds it `result.slots` + `prefs.preferred_focus_window`).
- Off-hardware: `FakeCalendarClient` + async `find_time_fn` stub returning multiple slots (some inside, some outside the focus window) + the plain-sqlite `ProductivityStore` fallback. → impact: Low.

Simplicity check: the change is one line in `schedule_task` — replace `slot = result.slots[0]` with `ranked = rank_slots_by_focus_window(result.slots, prefs.preferred_focus_window, prefs.timezone); slot = ranked[0]`. No new data models. The Areas-drop sweep is pure subtraction + a call-site rename. No new abstraction.

## Prerequisites

- Specs complete: **M8-d-b** (frozen seam), **F1 CAL-prefs amendment** (`rank_slots_by_focus_window` + `CalPrefs.preferred_focus_window`), **F0 M8-d-a-areas-drop** (no `area_id`), **F0 M8-d-a2-projects** (`tasks_manifest`).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/schedule_task.py` | modify | SURGICAL: replace `slot = result.slots[0]` with focus-window-ranked pick via `rank_slots_by_focus_window(result.slots, prefs.preferred_focus_window, prefs.timezone)`; import the helper |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` | modify | sweep: confirm `task_schedule`'s `update_task` call passes NO `area_id` (Areas-drop); no other change |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` | modify | rename the `task.schedule` wiring call site `productivity_manifest` → `tasks_manifest`; re-baseline tool count assertion to 23 (22 + `task.schedule`) |
| `/Users/artemis-build/artemis/tests/test_time_blocking_seam.py` | modify | add focus-window slot-pick tests; update manifest-shape assertion to `tasks_manifest` + 23 tools; drop any `area_id` usage |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Focus-window-biased slot-pick in `schedule_task`** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/schedule_task.py` (SURGICAL modify) —

  Add the import: `from artemis.modules.calendar.preferences import rank_slots_by_focus_window` (the helper added by the CAL-prefs amendment; bind to its actual exported name if it differs).

  In the frozen `schedule_task` body, the step that currently reads (frozen Task 1 step 5):
  ```python
  slot = result.slots[0]   # earliest
  ```
  becomes:
  ```python
  # X2: bias to the preferred focus window — earliest slot WITHIN the window, else earliest overall.
  ranked = rank_slots_by_focus_window(result.slots, prefs.preferred_focus_window, prefs.timezone)
  slot = ranked[0]
  ```
  Nothing else in `schedule_task` changes: the empty-`result.slots` early-return (frozen step 4) still runs BEFORE this (so `ranked` is never empty), the `[Task] {title}` block creation, the link-write, and the `ScheduleTaskResult` return are unchanged. `prefs: CalPrefs` is already a parameter of `schedule_task` (frozen signature) — no signature change.

  **Invariant:** `rank_slots_by_focus_window` is a pure reordering — it returns the same slots, never drops or fabricates one. `ranked[0]` is therefore always a real `find_time` slot (no double-booking risk: the focus-window bias only re-orders already-free slots). If the focus-window band contains no slot, `ranked` is the original chronological order and `ranked[0]` is the earliest overall (the frozen behaviour) — graceful fallback.

  — done when: `uv run mypy --strict src` passes; with an async `find_time_fn` stub returning slots `[08:30, 10:00, 14:00]` and `preferred_focus_window=("09:00","12:00")`, `await schedule_task(...)` picks the `10:00` slot (earliest WITHIN the window, not the earlier 08:30 outside it); with a focus window `("09:00","12:00")` and all slots outside it (`[14:00, 16:00]`), it picks `14:00` (earliest overall — fallback); empty `slots` still returns `scheduled=None` (frozen behaviour preserved).

- [ ] **Task 2: Areas-drop sweep in `task_schedule`** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` (modify) —

  Confirm (and correct if present) that the `task_schedule` link-write call is:
  ```python
  store.update_task(args.task_id, calendar_event_id=result.scheduled.event_id, scheduled_block=result.scheduled.start_dt)
  ```
  with NO `area_id` kwarg (Areas-drop removed it from `update_task`'s signature). `task_complete`'s link-clear path (`clear_task_schedule_link`) is unaffected (it never used `area_id`). No other change to `tools.py`.

  — done when: `uv run mypy --strict src` passes; `grep -n "area_id" src/artemis/modules/productivity/tools.py` returns zero hits; `task_schedule`/`task_complete` are still `async def` (ADR-016).

- [ ] **Task 3: Manifest call-site rename + tool-count re-baseline** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` (modify) —

  Per F0's projects-split, `task.schedule` rides the `tasks_manifest`. Update this spec's wiring so the `task.schedule` `ToolSpec` is added to `tasks_manifest`'s tools list (not a `productivity_manifest`). The `init_schedule_fn`/`init_write_tools` calls stay as the frozen M8-d-b specified, now invoked inside `tasks_manifest`.

  **Tool-count re-baseline (post-Areas-drop):** the M8-d-a base is **22** (after Areas-drop removed 8 tools). `tasks_manifest` carries ~16 task/suggestion tools; `projects_manifest` carries ~5 project tools (22 total across the two). This spec adds exactly ONE tool — `task.schedule` — to `tasks_manifest`. So `tasks_manifest`'s tool count goes from its post-split baseline to **+1**. The cumulative assertion is **relative**: assert `tasks_manifest` after this spec has its split-baseline count + 1 (the `task.schedule` entry is present; `task.complete` is still present). The fq id of `task.schedule` is **`tasks.schedule`** (manifest `tasks` + bare tool name `schedule`, per the projects-split fq-id convention — confirm whether the bare name is `"schedule"` or the dotted `"task.schedule"` as built by M8-d-a2, and use the form that yields fq id `tasks.schedule`).

  (The frozen M8-d-b "30 → 31" count is pre-Areas-drop and is superseded by this re-baseline.)

  — done when: `uv run mypy --strict src` passes; the `task.schedule` tool is on `tasks_manifest` with fq id `tasks.schedule`; `tasks_manifest` includes both `task.schedule` and `task.complete`; the deprecated `productivity_manifest` alias still resolves (no import break for any not-yet-updated caller).

- [ ] **Task 4: Tests** — files: `/Users/artemis-build/artemis/tests/test_time_blocking_seam.py` (modify) —

  Add focus-window slot-pick tests + update manifest assertions:
  - **Focus-window pick — within window:** async `find_time_fn` stub returns slots at `08:30`, `10:00`, `14:00` (same day, ISO-8601); `CalPrefs(preferred_focus_window=("09:00","12:00"), ...)`; `await schedule_task(...)` → the created block's `start_dt` is the `10:00` slot (earliest within window), NOT `08:30`.
  - **Focus-window pick — fallback:** all slots outside the window (`14:00`, `16:00`); `await schedule_task(...)` → picks `14:00` (earliest overall).
  - **Focus-window pick — empty slots:** `find_time_fn` returns `[]` → `scheduled=None` (regression: frozen behaviour preserved).
  - **`task_schedule` link write** (regression from frozen): writes `calendar_event_id`/`scheduled_block`; NO `area_id` referenced anywhere in the test.
  - **Manifest shape:** `tasks_manifest(store, schedule_fn, write_tools, registry).tools` includes `task.schedule` (fq id `tasks.schedule`) and `task.complete`; assert the count is the post-split tasks baseline + 1; assert `"area"` does not appear in any tool name.

  — done when: `uv run pytest -q tests/test_time_blocking_seam.py` passes AND `uv run mypy --strict src tests/test_time_blocking_seam.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/calendar/schedule_task.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_time_blocking_seam.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_time_blocking_seam.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_time_blocking_seam.py` | Test gate |
| `grep -rn "area_id" src/artemis/modules/calendar/schedule_task.py src/artemis/modules/productivity/tools.py` | Sweep gate — zero hits |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/calendar/schedule_task.py`, `src/artemis/modules/productivity/tools.py`, `src/artemis/modules/productivity/manifest.py`, `tests/test_time_blocking_seam.py` |
| `git commit` | `"feat: M8-d-b focus-window slot-pick + Areas-drop sweep (tasks_manifest, no area_id)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | Fakes only; real Google write is GATED on-Mini (frozen M8-d-b Task 5) |

## Specialist Context

### Security

- The focus-window ranking only re-orders already-free slots from `find_time`; it cannot introduce a double-booking (the busy-interval exclusion is `find_time`'s job, untouched). `schedule_task` remains structurally self-only (no attendees field — frozen invariant preserved). The link-write still happens only after a confirmed Google write (frozen ordering preserved). [apex-security note: confirm `rank_slots_by_focus_window` is a pure reordering that never fabricates a slot outside the returned free set.]
- Areas-drop reduces surface (no `area_id` column/kwarg). No new external-effect tool.

### Performance

- The ranking is an O(n) partition over ≤ a handful of `find_time` slots — negligible. No extra I/O; the change is purely in-memory slot ordering.

### Accessibility

(none — no frontend)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/calendar/schedule_task.py` | Document the focus-window slot-pick (earliest-within-window, else earliest-overall) replacing bare `slots[0]`; note it reuses the CAL-prefs ranking helper |
| Inline | `src/artemis/modules/productivity/manifest.py` | Note `task.schedule` rides `tasks_manifest` (fq id `tasks.schedule`) post-projects-split |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_time_blocking_seam.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_time_blocking_seam.py` → verify: focus-window pick chooses earliest-within-window; fallback to earliest-overall when none in window; empty-slots returns `scheduled=None`; `task_schedule` link-write has no `area_id`; `tasks_manifest` carries `task.schedule` (fq id `tasks.schedule`) + `task.complete`; no `area` tool names.
- [ ] `grep -rn "area_id" src/artemis/modules/calendar/schedule_task.py src/artemis/modules/productivity/tools.py` → verify: zero hits.
- [ ] `uv run python -c "from artemis.modules.calendar.schedule_task import schedule_task; from artemis.modules.calendar.preferences import rank_slots_by_focus_window; print('ok')"` → verify: prints `ok`.

## Progress
_(Coding mode writes here — do not edit manually)_
