---
spec: m8-d-c1-wake-digest
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave F1 · AMENDS M8-d-c1 (frozen: m8-d-c1-hooks.md). Re-specs the three productivity hooks to the
     wake-triggered rhythm per Tasks decisions T1 + T2 (LOCKED 2026-06-23):
       - Morning digest fires on the daily WAKE signal (fixed-time fallback), overdue folded in (T2).
       - Weekend review fires on Saturday WAKE (day-gated).
       - Week-ahead fires Sunday ~19:00 (clock).
     Builds on F0 M6-wake-trigger (HookSpec.wake/wake_fallback_time/wake_day_gate + Heartbeat.note_wake),
     F0 Areas-drop (no list_areas / area_count), F0 projects-split (tasks_manifest), and X3 runtime-config
     (schedule tunables). This is the re-spec the roadmap's Wave F1 row (M8-d-c1 wake-digest) names. -->

# Spec: M8-d-c1-wake-digest — wake-triggered productivity hooks (Morning digest on wake / Weekend review on Sat-wake / Week-ahead Sun-evening)

**Identity:** Re-specs the three Tier-1 productivity proactive hooks from the frozen interval/daily-cron rhythm to the wake-triggered rhythm (T1): `productivity_morning_digest` (wake hook + fixed-time fallback, overdue folded in per T2), `productivity_weekend_review` (Saturday-gated wake hook), and `productivity_week_ahead` (Sunday-evening clock hook). All `check_ref`s stay synchronous, LLM-free, counts+IDs-only; the separate hourly overdue-nudge interval hook is dropped (overdue rides the morning digest).
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (Tasks T1/T2 LOCKED) · docs/technical/modules/productivity.md §E · docs/technical/adr/ADR-006-two-tier-proactivity.md · supersedes the rhythm in docs/changes/m8-d-c1-hooks.md.

## Assumptions

- **M8-d-c1 (frozen `m8-d-c1-hooks.md`)** is the spec amended: `src/artemis/modules/productivity/hooks.py` exists with `make_morning_plan_check`, `make_overdue_nudge_check`, `make_weekly_review_check`, `build_productivity_hooks(store)`, `register_productivity_templates(registry)`, `_today_iso()`, `_week_iso()`. This re-spec REPLACES the three frozen hook definitions + their factories with the wake-triggered set. If the frozen M8-d-c1 has not yet been built, these deltas fold into its build directly (the coder builds the wake-rhythm hooks from the start). → impact: Stop (this is a rhythm re-spec of the same module file; symbol names below are the post-amendment canonical set).
- **F0 M6-wake-trigger** complete: `HookSpec` carries `wake: bool = False`, `wake_fallback_time: str | None = None`, `wake_day_gate: int | None = None`; the M6-a `model_validator` admits *exactly one of* `interval_seconds` / `cron` / `wake=True`; `Heartbeat.note_wake(now_wall)` sets the daily wake latch and `_wake_due` dispatches a wake hook at most once per wall-clock day (on wake OR at fallback time, never both), day-gated by `wake_day_gate`. → impact: Stop (the morning digest + weekend review are `wake=True` hooks; the single-fire + day-gate machinery is M6-wake's, not re-implemented here).
- **F0 M8-d-a-areas-drop** complete: the `areas` table + `area_id` are removed; `ProductivityRepository` has NO `list_areas` / `area_contents` methods. The frozen `make_weekly_review_check` called `store.list_areas()` and emitted an `"area_count"` payload key — both are removed here (Areas-drop sweep). → impact: Stop (a `list_areas` call would be an `AttributeError` post-areas-drop; the weekly/weekend payload drops `area_count`).
- **F0 M8-d-a2-projects** complete: the single `productivity_manifest` factory is split into `tasks_manifest(store, schedule_fn, write_tools, registry)` (carries `task.*` + `suggestion.*` tools + these proactive hooks) and `projects_manifest(store)`. The productivity hooks ride the **tasks** manifest (`name="tasks"`, `data_scope=OWNER_PRIVATE`). `productivity_manifest` remains as a transitional alias for `tasks_manifest`. This spec wires `proactive_hooks=build_productivity_hooks(store)` into `tasks_manifest`. → impact: Stop (the hook-wiring edit targets `tasks_manifest`; tool count is unchanged by this spec — hooks add no tools).
- **X3 runtime-config** complete: `get_runtime_config()` from `artemis.runtime_config` exposes `tasks.morning_digest_fallback_time` (`"08:00"`), `tasks.weekend_review_day` (`5` = Saturday), `tasks.week_ahead_time` (`"19:00"`), `tasks.week_ahead_day` (`6` = Sunday). The hook schedule values read from here at `build_productivity_hooks` call time (composition), not per-tick. → impact: Caution (a config change requires a manifest/Heartbeat rebuild — acceptable for daemon-scope schedule config).
- **M6-a** complete: `HookResult.of(payload, *, dedup_value)` / `HookResult.miss()`; the `OWNER_PRIVATE ⇒ tier==1` `ModuleManifest` validator; the M6-a minimal cron evaluator supports ONLY the daily `"M H * * *"` pattern and raises `ValueError` on a day-of-week field. → impact: Stop (the week-ahead hook uses a daily cron `"0 19 * * *"` + a Sunday-gated `dedup_value`, NOT a day-of-week cron, because the evaluator rejects day-of-week fields).
- **M6-b** complete: `TemplateRegistry.register(name, fn)`; `needs_llm=True` hooks are rendered by M6-b's batched LLM call from the hit payload; `needs_llm=False` hooks use a registered template. → impact: Stop (the template-registration seam exists; this spec registers templates for any `needs_llm=False` hook).
- All `check_ref` implementations stay **synchronous, LLM-free, deterministic** `ProductivityStore` reads, wrapped in `try/except Exception → HookResult.miss()` (degrade-don't-crash; a locked store raises `ScopeLockedError`, caught here). Payloads are **counts + UUID IDs ONLY** — never task titles/notes/raw_context (Seam 5 LLM-injection boundary). → impact: Stop (importing any model port into `hooks.py` is a build error; a `check_ref` that emits a title violates the payload-safety invariant).
- Off-hardware: `FakeKeyProvider(owner_unlocked=True)` + plain-sqlite fallback (M8-d-a pattern); a fake `wall_clock` + manual `Heartbeat.note_wake()` drive the wake/fallback paths deterministically (the M6-wake test harness). → impact: Low.

Simplicity check: considered keeping the morning digest as a daily cron and adding wake only as an "earlier-trigger" optimisation — rejected; T1 makes wake the primary trigger with the fixed time as fallback, which is exactly the M6-wake `wake=True` + `wake_fallback_time` contract, so no new mechanism is needed. Considered a wake hook for the Sunday week-ahead — rejected; week-ahead is a fixed evening clock (not tied to first-interaction), so a daily cron + a Sunday `dedup_value` gate is simpler and reuses the M6-a cron path with no day-of-week cron (which the evaluator forbids). Overdue folds into the morning digest payload (T2) rather than a separate hourly interval hook — one fewer hook, one fewer interruption channel.

## Prerequisites

- Specs complete: **M8-d-c1 (frozen)** (the `hooks.py` module amended — or this folds into its build), **F0 M6-wake-trigger** (`HookSpec.wake`/`wake_fallback_time`/`wake_day_gate` + `Heartbeat.note_wake`/`_wake_due`), **F0 M8-d-a-areas-drop** (no `list_areas`), **F0 M8-d-a2-projects** (`tasks_manifest`), **X3-runtime-config** (schedule tunables), **M6-a** (`HookSpec`/`HookResult`/cron evaluator/validator), **M6-b** (`TemplateRegistry`).
- Environment: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/hooks.py` | modify | replace the three frozen hook factories with `make_morning_digest_check` (overdue folded in), `make_weekend_review_check` (no `list_areas`), `make_week_ahead_check` (Sunday-gated); re-spec `build_productivity_hooks(store)` to the wake/cron rhythm; add `_sunday_iso()`; drop `make_overdue_nudge_check` |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` | modify | wire `proactive_hooks=build_productivity_hooks(store)` into `tasks_manifest` (F0 projects-split); `register_productivity_templates(registry)` call unchanged in shape; tool count unchanged by this spec |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` | modify | re-export unchanged in shape (hooks are internal); confirm `tasks_manifest` re-export carries the wired hooks |
| `/Users/artemis-build/artemis/tests/test_productivity_hooks.py` | modify | replace the frozen hook tests with wake-path/fallback-path/day-gate/Sunday-gate tests + the dropped-area assertions + the folded-overdue assertion |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

### Phase 1 — Re-spec the hook factories to the wake-triggered rhythm

- [ ] **Task 1: Re-spec `hooks.py` — morning digest (wake + fallback, overdue folded) + weekend review (Sat-wake) + week-ahead (Sun-evening)** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/hooks.py` (modify) —

  Imports unchanged in spirit: `HookSpec` from `artemis.manifest`; `HookResult` from `artemis.proactive.hook_types`; `ProductivityStore` from `artemis.modules.productivity.store`; `TemplateRegistry` from `artemis.proactive.hit_handler`; `get_runtime_config` from `artemis.runtime_config`. **No model imports; no Google imports.**

  **`make_morning_digest_check(store: ProductivityStore) -> Callable[[], HookResult]`** (replaces `make_morning_plan_check`; overdue folded in per T2):
  1. `today = store.today_tasks()`.
  2. `overdue = store.overdue_tasks()`.
  3. If `len(today) == 0 and len(overdue) == 0` → `HookResult.miss()`.
  4. Else → `HookResult.of({"today_count": len(today), "overdue_count": len(overdue), "today_task_ids": [t["id"] for t in today], "overdue_task_ids": [t["id"] for t in overdue]}, dedup_value=_today_iso())`.
  Wrap the body in `try/except Exception → HookResult.miss()` + WARNING log (degrade-don't-crash; `ScopeLockedError` caught here).

  **`make_weekend_review_check(store: ProductivityStore) -> Callable[[], HookResult]`** (replaces `make_weekly_review_check`; Areas-drop sweep — **no `list_areas`, no `area_count`**):
  1. `active_projects = store.list_projects(status="active")`.
  2. `overdue = store.overdue_tasks()`.
  3. `has_content = len(active_projects) > 0 or len(overdue) > 0`.
  4. If `not has_content` → `HookResult.miss()`.
  5. Else → `HookResult.of({"project_count": len(active_projects), "overdue_count": len(overdue), "project_ids": [p["id"] for p in active_projects]}, dedup_value=_week_iso())`.
  Wrap in `try/except Exception → HookResult.miss()` + log. **Do NOT call `store.list_areas()` (removed in F0 areas-drop) and do NOT emit `"area_count"`.**

  **`make_week_ahead_check(store: ProductivityStore) -> Callable[[], HookResult]`** (NEW; Sunday-evening look-ahead):
  1. `import datetime`; `now = datetime.datetime.now(datetime.timezone.utc)`; `cfg = get_runtime_config()`.
  2. **Sunday gate:** if `now.weekday() != cfg.tasks.week_ahead_day` (default `6` = Sunday) → return `HookResult.miss()` (the daily cron fires every evening; this gate restricts the *hit* to Sundays — see Task 2 rationale).
  3. `upcoming = store.upcoming_tasks(days=7)`.
  4. `active_projects = store.list_projects(status="active")`.
  5. If `len(upcoming) == 0 and len(active_projects) == 0` → `HookResult.miss()`.
  6. Else → `HookResult.of({"upcoming_count": len(upcoming), "project_count": len(active_projects), "upcoming_task_ids": [t["id"] for t in upcoming], "project_ids": [p["id"] for p in active_projects]}, dedup_value=_sunday_iso())`.
  Wrap in `try/except Exception → HookResult.miss()` + log.

  **Helpers:**
  - `_today_iso() -> str`: `datetime.now(timezone.utc).date().isoformat()` (unchanged from frozen).
  - `_week_iso() -> str`: ISO week `f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"` (unchanged from frozen) — the weekend-review per-week dedup.
  - `_sunday_iso() -> str` (NEW): the ISO week string for the current week, used as the week-ahead dedup so the hook fires at most once on a given Sunday (combined with the Sunday gate inside `make_week_ahead_check`). Implementation = same body as `_week_iso()` (one dedup per ISO week); naming distinct for clarity at the call site.

  **Drop `make_overdue_nudge_check` entirely** (T2: overdue folds into the morning digest; no separate hourly interruption).

  — done when: `uv run mypy --strict src` passes; `make_morning_digest_check(store)()` on a store with 1 overdue task returns `hit=True` with `overdue_count >= 1` AND `today_count` present (overdue folded in); `make_weekend_review_check(store)()` payload has NO `"area_count"` key and the factory makes NO `list_areas` call (grep-clean); `make_week_ahead_check(store)()` returns `HookResult.miss()` on a non-Sunday `wall_clock` and a hit on a Sunday with content; `make_overdue_nudge_check` no longer exists (`AttributeError` on import).

- [ ] **Task 2: Re-spec `build_productivity_hooks` to the wake/cron rhythm** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/hooks.py` (modify, same file) —

  Read the schedule tunables once: `cfg = get_runtime_config().tasks`.

  Construct and return the three `HookSpec`s:

  ```python
  [
      HookSpec(
          name="productivity_morning_digest",
          wake=True,                                   # T1: fires on the daily wake signal (M6-wake)
          wake_fallback_time=cfg.morning_digest_fallback_time,   # X3 default "08:00" — fires here if no wake by then
          urgency="normal",
          needs_llm=True,                              # M6-b composes the digest from today/overdue counts
          tier=1,                                      # OWNER_PRIVATE — M6-a validator
          dedup_key="prod_morning_digest",
          check_ref=make_morning_digest_check(store),
      ),
      HookSpec(
          name="productivity_weekend_review",
          wake=True,                                   # T1: fires on Saturday's wake
          wake_day_gate=cfg.weekend_review_day,        # X3 default 5 = Saturday (M6-wake day-gate)
          urgency="low",                               # digest path, not an interruption
          needs_llm=True,                              # M6-b composes the weekly review from project/overdue payload
          tier=1,
          dedup_key="prod_weekend_review",
          check_ref=make_weekend_review_check(store),
      ),
      HookSpec(
          name="productivity_week_ahead",
          # M6-a's minimal cron evaluator supports ONLY "M H * * *" (daily) and raises ValueError on a
          # day-of-week field. So we use a DAILY evening cron and restrict the *hit* to Sundays inside
          # check_ref (the Sunday gate in make_week_ahead_check) + a per-week dedup_value. This fires the
          # cron every evening but only HITS on Sunday — a wake hook would be wrong here (week-ahead is a
          # fixed evening clock, not tied to first-interaction-of-day).
          cron=f"{int(cfg.week_ahead_time.split(':')[1])} {int(cfg.week_ahead_time.split(':')[0])} * * *",  # "0 19 * * *" from X3 "19:00"
          urgency="low",
          needs_llm=True,                              # M6-b composes the week-ahead from upcoming/project payload
          tier=1,
          dedup_key="prod_week_ahead",
          check_ref=make_week_ahead_check(store),
      ),
  ]
  ```

  **Cron format note:** `cfg.week_ahead_time` is `"HH:MM"`; build the `"M H * * *"` string as `f"{minute} {hour} * * *"` (M6-a evaluator order is minute-then-hour). Default `"19:00"` → `"0 19 * * *"`. (Keep this a small inline parse; do not introduce a cron-builder dependency.)

  **`register_productivity_templates(registry: TemplateRegistry) -> None`:** all three hooks are `needs_llm=True`, so M6-b's batched LLM renders them — **no `needs_llm=False` template to register** (the frozen overdue-nudge template is dropped with the hook). Keep the function as a no-op (or register nothing) for call-site stability; document that v1 has no template-path productivity hook. (If a `needs_llm=False` hook is reintroduced later, register here.)

  **Payload-safety note (inline comment):** every `check_ref` payload contains ONLY counts + task/project UUIDs — never titles/notes/raw_context (Seam 5 LLM-injection boundary). M6-b v1 renders counts-only briefings (it has no `ProductivityStore` access for ID-based enrichment — same limitation the frozen spec's F11 fix recorded).

  — done when: `uv run mypy --strict src` passes; `build_productivity_hooks(store)` returns 3 `HookSpec`s; `productivity_morning_digest` has `wake=True` + `wake_fallback_time` set + no `interval_seconds`/`cron`; `productivity_weekend_review` has `wake=True` + `wake_day_gate=5`; `productivity_week_ahead` has `cron="0 19 * * *"` (parses under M6-a's `"M H * * *"` evaluator without `ValueError`) + no `wake`; all three `tier=1`, `needs_llm=True`; no `productivity_overdue_nudge` in the set.

### Phase 2 — Wire into the tasks manifest

- [ ] **Task 3: Wire hooks into `tasks_manifest`** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py`, `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` (modify) —

  In `tasks_manifest(store, schedule_fn, write_tools, registry)` (the F0 projects-split factory; `productivity_manifest` is its transitional alias):
  ```python
  from artemis.modules.productivity.hooks import build_productivity_hooks, register_productivity_templates

  register_productivity_templates(registry)        # no-op in v1 (all hooks needs_llm=True) — call kept for stability
  hooks = build_productivity_hooks(store)
  ```
  Set `proactive_hooks=hooks` on the `tasks_manifest` `ModuleManifest` (the `projects_manifest` keeps `proactive_hooks=[]`). SURGICAL: touch ONLY the `proactive_hooks` wiring + the `register_productivity_templates` call. Do NOT change the tools list, manifest name/version/description, `data_scope`, or permissions. **Tool count is unchanged by this spec** (hooks add no tools; the post-areas-drop tasks-manifest tool count is established by F0 + M8-d-b — this spec does not assert a new count).

  `__init__.py`: confirm the `tasks_manifest` re-export now surfaces a manifest whose `proactive_hooks` has length 3; no signature change beyond F0.

  — done when: `uv run mypy --strict src` passes; `tasks_manifest(store, schedule_fn, write_tools, registry).proactive_hooks` has length 3; the M6-a `ModuleManifest` validator does not raise (`OWNER_PRIVATE ⇒ tier==1` holds for all three); `projects_manifest(store).proactive_hooks == []`; `uv run python -c "from artemis.modules.productivity import tasks_manifest; print('ok')"` prints `ok`.

### Phase 3 — Tests

- [ ] **Task 4: Re-spec the hook tests to the wake/cron rhythm** — files: `/Users/artemis-build/artemis/tests/test_productivity_hooks.py` (modify) — typed pytest. Fixtures: `FakeKeyProvider({"owner-private": os.urandom(32)}, owner_unlocked=True)` + `Settings(data_root=tmp_path)` + `ProductivityStore(settings, fake_key)` (plain-sqlite fallback); a `TemplateRegistry()`; a fake `wall_clock` + a real `Heartbeat` over a `ToolRegistry` for the wake/cron firing tests (the M6-wake harness).

  **`check_ref` behaviour:**
  - `make_morning_digest_check` with no tasks today and no overdue → `HookResult.miss()`.
  - `make_morning_digest_check` with 2 today + 1 overdue → `hit=True`; `payload["today_count"] == 2`; `payload["overdue_count"] == 1`; payload has `"today_task_ids"` + `"overdue_task_ids"` (UUID lists); **overdue is folded in (T2) — assert both counts present in the single digest payload**; no title strings in payload.
  - `make_weekend_review_check` with no projects + no overdue → `HookResult.miss()`.
  - `make_weekend_review_check` with 2 active projects → `hit=True`; `payload["project_count"] == 2`; **assert `"area_count"` NOT in payload (Areas-drop)**; `dedup_value` matches `"YYYY-WNN"`.
  - `make_week_ahead_check` on a **non-Sunday** `wall_clock` (monkeypatch the module's `datetime.now` or inject the clock) → `HookResult.miss()` regardless of content (Sunday gate).
  - `make_week_ahead_check` on a **Sunday** with 3 upcoming tasks → `hit=True`; `payload["upcoming_count"] == 3`; `dedup_value` matches the ISO-week format.

  **Payload content safety:** for every hook's `hit=True` payload, assert none of `"title"`, `"notes"`, `"raw_context"`, `"area_count"` appear as keys (counts + IDs only — Seam 5 boundary + Areas-drop).

  **HookSpec construction:**
  - `build_productivity_hooks(store)` returns 3 hooks named exactly `{"productivity_morning_digest", "productivity_weekend_review", "productivity_week_ahead"}`.
  - All three `tier == 1`, `needs_llm == True`.
  - `productivity_morning_digest`: `wake is True`, `wake_fallback_time == "08:00"` (X3 default), no `cron`, no `interval_seconds`.
  - `productivity_weekend_review`: `wake is True`, `wake_day_gate == 5`.
  - `productivity_week_ahead`: `cron == "0 19 * * *"` (parses under M6-a `"M H * * *"` without `ValueError` — assert), `wake is False`.
  - No hook named `productivity_overdue_nudge` (dropped).

  **Wake firing (morning digest) — integration via Heartbeat (M6-wake harness):**
  - Register `tasks_manifest(...)` on a `ToolRegistry`; build `Heartbeat(registry, FakeKeyProvider(owner_unlocked=True), wall_clock=fake_clock)`; seed the store with a due task.
  - `wall_clock` at 07:00 (before fallback), no `note_wake` → `tick()` does NOT fire the morning digest. Call `heartbeat.note_wake(07:05)` → next `tick()` fires it once (hit in `tick().hits`); a second same-day `tick()` does NOT re-fire (M6-wake single-fire).
  - Fallback path: fresh day, no `note_wake`, `wall_clock` at 08:01 → `tick()` fires the morning digest once (fallback).

  **Weekend review day-gate:**
  - On a Wednesday `wall_clock` with `note_wake` → weekend review does NOT fire; on a Saturday with `note_wake` → fires once.

  **Week-ahead Sunday gate:**
  - With `wall_clock` cron-due at 19:00 on a non-Sunday → `make_week_ahead_check` returns miss (so no hit even though the cron is due); on a Sunday at 19:00 with content → hit.

  **Tier-1 queueing:**
  - With `FakeKeyProvider(owner_unlocked=False)` and a wake signal → `productivity_morning_digest`'s `check_ref` is NOT called; fq name in `tick().tier1_skipped`.

  **Degrade (ScopeLockedError):**
  - `make_morning_digest_check(store)()` where the store would raise `ScopeLockedError` → returns `HookResult.miss()` (swallowed, no propagation).

  **Manifest integration:**
  - `tasks_manifest(store, schedule_fn, write_tools, registry).proactive_hooks` has length 3; no `ValidationError`.
  - `projects_manifest(store).proactive_hooks == []`.

  — done when: `uv run pytest -q tests/test_productivity_hooks.py` passes AND `uv run mypy --strict src tests/test_productivity_hooks.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 5 (GATED — on-hardware):** On the Mini, vault mounted + unlocked: seed a real `ProductivityStore`; confirm `productivity_morning_digest` fires on a real `Heartbeat.note_wake` + tick (and via the fallback when no wake by 08:00); `productivity_weekend_review` fires only on Saturday's wake; `productivity_week_ahead` fires only on Sunday 19:00; confirm Tier-1 queueing while the vault is locked; confirm payloads carry correct counts + IDs and no titles. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/hooks.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_productivity_hooks.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_productivity_hooks.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_productivity_hooks.py` | Test gate |
| `uv run pytest -q tests/test_heartbeat_wake.py tests/test_heartbeat_scheduler.py` | Regression gate (M6-wake + M6-a still green) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/productivity/hooks.py`, `src/artemis/modules/productivity/manifest.py`, `src/artemis/modules/productivity/__init__.py`, `tests/test_productivity_hooks.py` |
| `git commit` | `"refactor: M8-d-c1 wake-triggered productivity hooks — morning digest (wake+fallback, overdue folded) / weekend review (Sat-wake) / week-ahead (Sun-evening)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir + slot_root (X3 config) resolution (off-hardware: tmp_path fixture) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No network; `check_ref` is deterministic, LLM-free |

## Specialist Context

### Security

- **Tier-1 enforcement unchanged:** all three hooks declare `tier=1` on the `OWNER_PRIVATE` tasks manifest. The M6-a `ModuleManifest` validator enforces `OWNER_PRIVATE ⇒ tier==1` at construction; the M6-a/M6-wake tick gate ensures no `check_ref` runs while the vault is locked. `note_wake` carries only a date — it cannot force-fire a Tier-1 hook while locked (the tier gate runs after due-evaluation; a locked wake hook is skipped-and-queued).
- **LLM-injection boundary (Seam 5):** `check_ref` payloads are counts + UUID lists only. Task titles/notes/`raw_context` are owner-authored but must not be forwarded raw into M6-b's batched LLM compositing prompt. Enforced by construction (the factories include only counts + ID lists). v1 briefings are counts-only (M6-b has no store access for ID enrichment).
- **No model calls in `check_ref`:** the factories are pure `ProductivityStore` reads. Importing any model/Google port into `hooks.py` is a build error (keep `hooks.py` free of `artemis.ports` / Google imports; mypy --strict catches accidental imports).
- **Degrade-don't-crash:** `ScopeLockedError` (mid-tick lock) is caught → `HookResult.miss()`; a hook failure never aborts the tick or `run_forever` (M6-a catch-and-miss pattern).

### Performance

- Each `check_ref` is one-to-three indexed SQL reads against the owner's task DB (hundreds–low-thousands of rows; the `due_at` partial index from M8-d-a keeps `today`/`overdue`/`upcoming` index-driven) — sub-millisecond.
- Cadence is far lower than the frozen rhythm: the morning digest fires at most once/day (wake or fallback), the weekend review once/week (Saturday wake), the week-ahead once/week (Sunday evening). The dropped hourly overdue-nudge removes the most frequent prior tick-cost. The week-ahead daily cron does one cheap Sunday-gate check (a weekday comparison) on the six non-Sunday evenings → returns miss with no DB read past the gate (move the gate BEFORE the store reads — done in `make_week_ahead_check` step 2).
- Payloads are small (counts + UUID lists) — minimal M6-b prompt-injection surface, zero egress risk.

### Accessibility

(none — no frontend in M8-d-c1)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/productivity/hooks.py` | Docstring each factory; document the wake-trigger rhythm (T1), the overdue-folded-into-morning-digest decision (T2), the Areas-drop (no `list_areas`/`area_count`), the Sunday-gate-on-a-daily-cron rationale (M6-a daily-only cron constraint), and the counts+IDs payload boundary |
| Inline | `src/artemis/modules/productivity/manifest.py` | Document that the productivity hooks ride the `tasks_manifest` (not `projects_manifest`) and that `register_productivity_templates` is a v1 no-op (all hooks `needs_llm=True`) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_productivity_hooks.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_productivity_hooks.py` → verify: morning digest folds overdue into one wake-triggered payload (both counts present); morning digest fires on `note_wake` and via the 08:00 fallback, single-fire per day; weekend review is Saturday-day-gated wake; week-ahead misses on non-Sunday and hits on Sunday 19:00; no `area_count` in any payload and no `list_areas` call; no `productivity_overdue_nudge` hook; all three `tier=1`/`needs_llm=True`; week-ahead `cron="0 19 * * *"` parses without `ValueError`; Tier-1 queueing when locked; `ScopeLockedError` degrades to miss; `tasks_manifest.proactive_hooks` length 3, `projects_manifest.proactive_hooks == []`; manifest validator passes.
- [ ] `uv run pytest -q tests/test_heartbeat_wake.py tests/test_heartbeat_scheduler.py` → verify: no regression in M6-wake / M6-a.
- [ ] `uv run python -c "from artemis.modules.productivity.hooks import build_productivity_hooks; print(len(build_productivity_hooks.__name__))"` → verify: exits 0 (import smoke).
- [ ] `uv run python -c "from artemis.modules.productivity import tasks_manifest, projects_manifest; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini, vault unlocked) morning digest fires on wake + fallback; weekend review on Sat-wake; week-ahead on Sun-evening; Tier-1 queueing under a locked vault; payloads counts+IDs only → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
