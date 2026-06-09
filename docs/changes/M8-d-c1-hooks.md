---
spec: m8-d-c1-hooks
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M8-d-c1 — Productivity proactive hooks (Morning-plan / Overdue-nudge / Weekly-review)

**Identity:** Adds the three Tier-1 proactive hooks to the Productivity `ModuleManifest`: `productivity_morning_plan` (daily, needs_llm=True), `productivity_overdue_nudge` (hourly, needs_llm=False), and `productivity_weekly_review` (weekly via interval_seconds, needs_llm=True). Implements per-hook `check_ref` factories, the `build_productivity_hooks(store)` assembler, and `register_productivity_templates(registry)` for the `needs_llm=False` hook.
→ why: see docs/technical/modules/productivity.md §E (hooks, LOCKED 2026-06-09) · docs/technical/adr/ADR-006-two-tier-proactivity.md · docs/technical/adr/ADR-011-spoke-source-of-truth.md

## Assumptions

- **M8-d-a** complete: `ProductivityRepository` (all CRUD methods, `create_suggestion`/`accept_suggestion`/`overdue_tasks`/`today_tasks`/`list_projects`/`list_areas`/`area_contents`), `ProductivityStore`, `productivity_manifest()`, and the `suggestions` table (with `source`, `status`, `raw_context` columns) all exist at `src/artemis/modules/productivity/`. The manifest's `proactive_hooks=[]` — this spec populates it. → impact: Stop.
- **M6-a** complete: `HookSpec` (extended, with `tier: Literal[0,1]`, `delivery: DeliverySpec | None`, `cron`/`interval_seconds`, `check_ref: Callable[[], HookResult]`), `HookResult` (`.miss()` / `.of(payload, *, dedup_value)`), the `OWNER_PRIVATE ⇒ tier==1` manifest validator, all from `artemis.manifest` / `artemis.proactive.hook_types`. The M6-a minimal cron evaluator supports ONLY the `"M H * * *"` pattern (daily); it raises `ValueError` on any other cron field (e.g. day-of-week `"0 9 * * 1"`). → impact: Stop (`weekly_review` MUST use `interval_seconds=604800` + `dedup_value=_week_iso()`, NOT a day-of-week cron).
- **M6-b** complete: `HitHandler` / `TemplateRegistry` — the `on_hits` seam is wired and templates are registered at composition time; M8-d-c1 registers a template per hook. `needs_llm=True` hooks have their payload rendered by the batched LLM call; `needs_llm=False` hooks use the template path. → impact: Stop (template registration seam must exist).
- **M6-c** complete: `NtfyDelivery` / Tier-1 queue — Tier-1 hooks are skipped-and-queued while the vault is locked; `tier1_sink` is wired at the `Heartbeat` composition root. → impact: Caution (correct Tier-1 behaviour is enforced by M6-a's tick gate; M8-d-c1 only declares the hooks — it does not wire the tick).
- All `check_ref` implementations in this spec are **deterministic and LLM-free** (Tier-1, data read from `ProductivityStore`). The LLM rendering of hit payloads rides M6-b's batched call at tick time. → impact: Stop (a `check_ref` that calls the model violates the M6-a contract; never import model ports here).
- `ProductivityStore` is injected at manifest construction time; hooks capture it in their `check_ref` closure at `build_productivity_hooks(store)` call time. No global state. → impact: Stop.
- Off-hardware: `check_ref` runs against a `FakeKeyProvider(owner_unlocked=True)` + plain-sqlite fallback (same M8-d-a pattern). Real SQLCipher round-trip is GATED on-hardware. → impact: Caution.
- The `ModuleManifest` `OWNER_PRIVATE ⇒ tier==1` validator (M6-a) will fail at construction if any hook has `tier=0` on the productivity manifest (`data_scope=OWNER_PRIVATE`). All three hooks must have `tier=1`. → impact: Stop.

Simplicity check: considered per-hook factory functions returning `(check_ref, HookSpec)` tuples as in CAL-c — adopted (same factory pattern). Considered inlining `check_ref` callables in `manifest.py` — rejected; `hooks.py` keeps the manifest thin and makes the check logic independently testable. No new dependencies beyond M8-d-a + M6-a/M6-b type imports.

## Prerequisites

- Specs complete: **M8-d-a** (ProductivityStore + repository + suggestions table), **M6-a** (HookSpec/HookResult/tier contract), **M6-b** (TemplateRegistry registration seam — needed to register hook templates).
- Specs this enables: **M8-d-c2** (capture + knowledge/memory — builds on the same `hooks.py` module; parked pending c1 completion).
- Environment: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/modules/productivity/hooks.py` | create | three `make_*_check` factories + `HookSpec` declarations + `build_productivity_hooks(store) -> list[HookSpec]` + `register_productivity_templates(registry: TemplateRegistry) -> None` |
| `src/artemis/modules/productivity/manifest.py` | modify | call `build_productivity_hooks(store)` + `register_productivity_templates(registry)` + pass the hook list into `ModuleManifest.proactive_hooks`; add `registry: TemplateRegistry` param to `productivity_manifest(store, registry)` |
| `src/artemis/modules/productivity/__init__.py` | modify | update re-export of `productivity_manifest` to reflect the new `registry` parameter |
| `tests/test_productivity_hooks.py` | create | off-hardware hook check_ref tests + Tier-1 queueing smoke + template rendering |

All paths are under `/Users/artemis-build/artemis/`.

## Tasks

### Phase 1 — Hook factories + TemplateRegistry registration

- [ ] **Task 1: Create `hooks.py` with three hook factories** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/hooks.py` —

  Import `HookSpec`, `HookResult` from `artemis.manifest` / `artemis.proactive.hook_types`. Import `ProductivityStore` from `artemis.modules.productivity.store`. Import `TemplateRegistry` from `artemis.proactive.hit_handler`. No model imports; no Google imports.

  **`make_morning_plan_check(store: ProductivityStore) -> Callable[[], HookResult]`**:

  Returns a `check_ref` callable. When called:
  1. Call `store.today_tasks()` → `today: list[dict]`.
  2. Call `store.overdue_tasks()` → `overdue: list[dict]`.
  3. If `len(today) == 0 and len(overdue) == 0` → return `HookResult.miss()`.
  4. Else → return `HookResult.of({"today_count": len(today), "overdue_count": len(overdue), "today_task_ids": [t["id"] for t in today], "overdue_task_ids": [t["id"] for t in overdue]}, dedup_value=_today_iso())`.

  Wrap the entire body in `try/except Exception` → on error log a warning and return `HookResult.miss()` (degrade-don't-crash; a locked store raises `ScopeLockedError` which is caught here).

  **`make_overdue_nudge_check(store: ProductivityStore) -> Callable[[], HookResult]`**:

  Returns a `check_ref` callable. When called:
  1. Call `store.overdue_tasks()` → `overdue: list[dict]`.
  2. If empty → return `HookResult.miss()`.
  3. Else → return `HookResult.of({"overdue_count": len(overdue), "overdue_task_ids": [t["id"] for t in overdue]}, dedup_value=f"{_today_iso()}-{len(overdue)}")`.

  Wrap in `try/except Exception` → `HookResult.miss()` + log (same degrade pattern).

  **`make_weekly_review_check(store: ProductivityStore) -> Callable[[], HookResult]`**:

  Returns a `check_ref` callable. When called:
  1. Call `store.list_projects(status="active")` → `active_projects: list[dict]`.
  2. Call `store.list_areas()` → `areas: list[dict]`.
  3. Call `store.overdue_tasks()` → `overdue: list[dict]`.
  4. `has_content = len(active_projects) > 0 or len(overdue) > 0`.
  5. If `not has_content` → return `HookResult.miss()`.
  6. Else → return `HookResult.of({"project_count": len(active_projects), "area_count": len(areas), "overdue_count": len(overdue), "project_ids": [p["id"] for p in active_projects]}, dedup_value=_week_iso())`.

  Wrap in `try/except Exception` → `HookResult.miss()` + log.

  **`_today_iso() -> str`**: `datetime.now(timezone.utc).date().isoformat()` — one dedup value per calendar day.

  **`_week_iso() -> str`**: ISO week string e.g. `"2026-W24"` — `f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"` where `d = datetime.now(timezone.utc).date()`. One dedup per calendar week. Used as `dedup_value` for `weekly_review` (the once-per-week gate, in lieu of a day-of-week cron).

  **`build_productivity_hooks(store: ProductivityStore) -> list[HookSpec]`**:

  Construct and return three `HookSpec` instances:

  ```python
  [
      HookSpec(
          name="productivity_morning_plan",
          cron="0 8 * * *",           # 08:00 daily — fire-if-past-and-not-yet-fired semantics (M6-a)
          urgency="normal",
          needs_llm=True,             # M6-b renders a personalised morning plan from today/overdue counts
          tier=1,                     # OWNER_PRIVATE module — enforced by M6-a manifest validator
          dedup_key="prod_morning_plan",
          check_ref=make_morning_plan_check(store),
      ),
      HookSpec(
          name="productivity_overdue_nudge",
          interval_seconds=3600,      # hourly check
          urgency="normal",
          needs_llm=False,            # template path; count + ids are deterministic
          tier=1,
          dedup_key="prod_overdue",
          check_ref=make_overdue_nudge_check(store),
      ),
      HookSpec(
          name="productivity_weekly_review",
          # M6-a's minimal cron evaluator supports only "M H * * *" (daily); it raises ValueError
          # on day-of-week fields. Weekly cadence is enforced by interval_seconds=604800 (7 days)
          # + dedup_value=_week_iso() inside check_ref (fires at most once per ISO week).
          interval_seconds=604800,
          urgency="low",              # batch-low→digest path (M6-b); not an interruption
          needs_llm=True,             # M6-b composes the weekly digest from project/area/overdue payload
          tier=1,
          dedup_key="prod_weekly_review",
          check_ref=make_weekly_review_check(store),
      ),
  ]
  ```

  **`register_productivity_templates(registry: TemplateRegistry) -> None`**:

  Register `needs_llm=False` templates only (the `overdue_nudge` hook):

  ```python
  registry.register(
      "productivity.productivity_overdue_nudge",
      lambda result: f"{result.payload.get('overdue_count', 0)} task(s) past their due date",
  )
  ```

  `needs_llm=True` hooks (morning_plan, weekly_review) do not need a template — M6-b's batched LLM call renders them. Document this inline.

  **Payload safety note (inline comment):** All `check_ref` payloads contain ONLY counts and task/project IDs (UUIDs). No titles, notes, or user-authored text ever enters a `check_ref` payload. This is the LLM injection boundary: task titles are owner-authored trusted content but they must not be forwarded raw to M6-b's batched LLM compositing prompt (the prompt-injection surface). The LLM call in M6-b must fetch full task details from `store` via the IDs in the payload if richer content is needed. Document: `# PAYLOAD: counts + IDs only — never raw task/project titles (LLM injection boundary; M6-b fetches details by ID)`.

  — done when: `uv run mypy --strict src` passes; `build_productivity_hooks(store)` returns a list of 3 `HookSpec`s; all have `tier=1`; exactly one has `needs_llm=False`; `weekly_review` has `interval_seconds=604800` (no `cron` field); `make_morning_plan_check(store)()` on a store with one overdue task returns `hit=True` with `overdue_count >= 1`; `make_overdue_nudge_check(store)()` on an empty store returns `hit=False`.

- [ ] **Task 2: Modify `manifest.py` to wire hooks** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` (SURGICAL modify) —

  Change the signature of `productivity_manifest` from `(store: ProductivityStore) -> ModuleManifest` to `(store: ProductivityStore, registry: TemplateRegistry) -> ModuleManifest`.

  Inside, add:
  ```python
  from artemis.modules.productivity.hooks import build_productivity_hooks, register_productivity_templates

  register_productivity_templates(registry)
  hooks = build_productivity_hooks(store)
  ```

  Replace `proactive_hooks=[]` with `proactive_hooks=hooks`.

  Update the re-export in `modules/productivity/__init__.py` — the `productivity_manifest` function signature changes; no other module in `__init__.py` changes.

  SURGICAL: touch ONLY the `proactive_hooks` wiring and the function signature. Do NOT change tools list, manifest name, version, description, `data_scope`, or permissions.

  — done when: `uv run mypy --strict src` passes; `productivity_manifest(store, registry).proactive_hooks` has length 3; the M6-a `ModuleManifest` validator does not raise (`OWNER_PRIVATE ⇒ tier==1` holds for all three hooks); `uv run python -c "from artemis.modules.productivity import productivity_manifest; print('ok')"` prints `ok`.

### Phase 2 — Tests

- [ ] **Task 3: Off-hardware tests** — files: `/Users/artemis-build/artemis/tests/test_productivity_hooks.py` — typed pytest. Fixture: `FakeKeyProvider({"owner-private": os.urandom(32)}, owner_unlocked=True)` + `Settings(data_root=tmp_path)` + `ProductivityStore(settings, fake_key)` (plain-sqlite fallback); a `TemplateRegistry()` instance.

  **Hook `check_ref` behaviour:**

  - `make_morning_plan_check` with NO tasks today and NO overdue → `HookResult.miss()`.
  - `make_morning_plan_check` with 2 tasks due today → `hit=True`; `payload["today_count"] == 2`; `dedup_value == _today_iso()`; payload contains `"today_task_ids"` (list of 2 UUIDs); payload does NOT contain any task title string.
  - `make_morning_plan_check` with 1 overdue task → `hit=True`; `payload["overdue_count"] == 1`.
  - `make_overdue_nudge_check` with no overdue tasks → `HookResult.miss()`.
  - `make_overdue_nudge_check` with 3 overdue tasks → `hit=True`; `payload["overdue_count"] == 3`; `dedup_value` contains `"3"`.
  - `make_weekly_review_check` with no projects and no overdue → `HookResult.miss()`.
  - `make_weekly_review_check` with 2 active projects → `hit=True`; `payload["project_count"] == 2`; `dedup_value` matches the ISO week string format (`"YYYY-WNN"`).

  **Payload content safety:**

  - Assert that for every hook's `HookResult.of(...)` payload when `hit=True`, none of `"title"`, `"notes"`, `"raw_context"` appear as keys (counts + IDs only). This is a structural guard for the LLM injection boundary.

  **HookSpec construction:**

  - `build_productivity_hooks(store)` returns 3 hooks.
  - All three have `tier == 1`.
  - Hook names are `{"productivity_morning_plan", "productivity_overdue_nudge", "productivity_weekly_review"}` (exact).
  - `productivity_morning_plan` has `needs_llm=True` and `cron="0 8 * * *"` (parses without `ValueError` under M6-a's `"M H * * *"` evaluator — assert).
  - `productivity_overdue_nudge` has `needs_llm=False` and `interval_seconds=3600`.
  - `productivity_weekly_review` has `needs_llm=True` and `interval_seconds=604800` (NOT a cron field — M6-a's evaluator raises `ValueError` on day-of-week; assert no `cron` attribute is set on this HookSpec); `urgency="low"`; `dedup_value` from its `check_ref` is `_week_iso()` format.

  **Manifest integration:**

  - `productivity_manifest(store, registry).proactive_hooks` has length 3.
  - No `ValidationError` raised (M6-a `OWNER_PRIVATE ⇒ tier==1` validator passes).
  - `productivity_manifest(store, registry).tools` is unchanged (30 tools — the tools list is NOT modified by this spec; assert `len(tools) == 30`).

  **Template registration:**

  - After `register_productivity_templates(registry)`, `registry.render("productivity.productivity_overdue_nudge", HookResult.of({"overdue_count": 3}))` returns a string containing `"3"` and does not raise.
  - The `needs_llm=True` hook names are NOT registered in the template registry (no key for `"productivity.productivity_morning_plan"` or `"productivity.productivity_weekly_review"`); unregistered keys fall back to the payload-free default (M6-b TemplateRegistry contract — assert the fallback does not contain any payload value).

  **Tier-1 queueing:**

  - Build a `ToolRegistry`, register the `productivity_manifest(store, registry)` manifest; build a `Heartbeat(registry, FakeKeyProvider(owner_unlocked=False))`.
  - Call `tick()` → `productivity_morning_plan`'s `check_ref` is NOT called (hook is skipped); fq name `"productivity.productivity_morning_plan"` appears in `tick().tier1_skipped`.
  - With `FakeKeyProvider(owner_unlocked=True)` and a store seeded with a due task → `check_ref` IS called; hit appears in `tick().hits`.

  **Degrade (ScopeLockedError):**

  - `make_morning_plan_check(store)()` where `store._get_conn()` would raise `ScopeLockedError` (locked provider) → returns `HookResult.miss()` (error swallowed; does not propagate).

  — done when: `uv run pytest -q tests/test_productivity_hooks.py` passes AND `uv run mypy --strict src tests/test_productivity_hooks.py` passes.

- [ ] **Task 4 (GATED — on-hardware):** On the Mini with vault mounted and owner unlocked: `build_productivity_hooks(store)` with a real `ProductivityStore`; seed with tasks/projects; confirm all three `check_ref`s fire via a real `Heartbeat.tick()` and the hit payloads carry correct counts and IDs; confirm Tier-1 queueing under a locked vault. Record in handoff. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/productivity/hooks.py` |
| Create | `/Users/artemis-build/artemis/tests/test_productivity_hooks.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_productivity_hooks.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_productivity_hooks.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/productivity/hooks.py`, `src/artemis/modules/productivity/manifest.py`, `src/artemis/modules/productivity/__init__.py`, `tests/test_productivity_hooks.py` |
| `git commit` | `"feat: M8-d-c1 productivity hooks — morning-plan, overdue-nudge, weekly-review (Tier-1 M6-a)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir path resolution (off-hardware: tmp_path fixture) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No network; `check_ref` is deterministic, LLM-free |

## Specialist Context

### Security

- **Tier-1 enforcement:** All three hooks declare `tier=1` on an `OWNER_PRIVATE` module. The M6-a `ModuleManifest` validator enforces `OWNER_PRIVATE ⇒ tier==1` at construction time — a misconfigured `tier=0` hook raises `ValidationError` before the manifest is used. The M6-a tick gate ensures no `check_ref` runs while the owner session is locked (no sensitive task read without an unlocked vault).
- **LLM injection boundary — payload sanitisation:** `check_ref` payloads contain ONLY counts and UUID lists. Task titles, notes, and `raw_context` are owner-authored trusted data BUT they must not be forwarded raw into M6-b's batched LLM compositing prompt (a `needs_llm=True` payload is embedded directly into the batched prompt). The boundary is enforced by construction — the factories only include counts + `task_id` lists. M6-b retrieves full task details by ID from the store if needed for rendering. This mirrors the CAL-c `_quarantine_stub` boundary for externally-authored calendar event titles.
- **No model calls in `check_ref`:** `check_ref` functions are pure `ProductivityStore` reads. Importing any model port into `hooks.py` is a build error. Enforce by keeping `hooks.py` free of `artemis.ports` / `artemis.models` imports (mypy --strict will catch accidental imports).
- **Degrade-don't-crash:** `ScopeLockedError` from a mid-tick lock event is caught and returns `HookResult.miss()`. A hook failure never aborts the tick or `run_forever` (M6-a catch-and-miss pattern).
- **M8-d-c2 email-capture flag (for c2 drafter):** `raw_context` from email-sourced suggestions is untrusted data. Any LLM-generative step that reads it MUST route through `artemis.untrusted` (DR-a quarantine) first — same as `gmail.md` and the CAL-c `_quarantine_stub`. M8-d-c1 does not touch the capture path; flag stands for c2.

### Performance

- `check_ref` is a read-only SQL query against the owner's task DB (hundreds to low-thousands of rows). At this scale, indexed queries (`due_at` partial index from M8-d-a) are sub-millisecond. The `ProductivityRepository(conn)` per-call pattern (M8-d-a design decision) is negligible at hook frequency (hourly at most).
- `morning_plan` fires once per day via cron (M6-a fire-if-past-and-not-yet-fired). `overdue_nudge` fires hourly — each tick is one indexed SQL query. `weekly_review` fires at most once per ISO week (interval_seconds=604800 + `_week_iso()` dedup).
- Payload is small (counts + UUID lists — no serialised task bodies) — zero egress risk and minimal M6-b prompt injection surface.

### Accessibility

(none — no frontend in M8-d-c1)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/productivity/hooks.py` | Docstring each factory; document Tier-1, payload-safety boundary, degrade pattern, and the interval_seconds weekly cadence rationale (M6-a daily-only cron constraint) |
| Inline | `src/artemis/modules/productivity/manifest.py` | Document the new `registry` param and the hooks wiring |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_productivity_hooks.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_productivity_hooks.py` → verify: all `check_ref` hit/miss scenarios pass; payload contains only counts + IDs (no title/notes strings); `build_productivity_hooks(store)` returns 3 `HookSpec`s all with `tier=1`; `weekly_review` has `interval_seconds=604800` (no cron); manifest validates without `ValidationError`; tools list remains 30; template registry registers only the `needs_llm=False` hook; Tier-1 queueing test: hook skipped when locked, runs when unlocked; `ScopeLockedError` degrades to miss — all pass.
- [ ] `uv run python -c "from artemis.modules.productivity import productivity_manifest, ProductivityStore; from artemis.proactive.hit_handler import TemplateRegistry; print(len(productivity_manifest.__code__.co_varnames))"` → verify: exits 0 (import smoke; signature change accepted).
- [ ] `uv run python -c "from artemis.modules.productivity.hooks import build_productivity_hooks; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini, vault unlocked) All three `check_ref`s fire via a real `Heartbeat.tick()` with a seeded task/project store; Tier-1 queueing confirmed under a locked vault → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
