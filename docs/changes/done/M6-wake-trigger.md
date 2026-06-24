---
spec: m6-wake-trigger
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave F0 · AMENDS M6-a. Implements Decision T1 (LOCKED): add a wake/intent trigger class to the
     heartbeat scheduler. event=wake ("good morning" / first-interaction detection) + per-day-of-week
     gating + fixed-time fallback. Reused by the Tasks Morning digest (M8-d-c1), Calendar daily briefing,
     and Weekend review. Surgical extension of the M6-a HookSpec contract + the due-evaluation loop. -->

# Spec: M6-wake-trigger — wake/intent trigger class for the heartbeat (event=wake + day-gate + fixed-time fallback)

**Identity:** Extend the M6-a `HookSpec` due-evaluation with a third trigger mode — `wake` — that fires a hook once per day on the first owner interaction of the day (the "good morning" signal), with a configurable fixed-time fallback if no wake is observed by a cutoff, and an optional day-of-week gate. The wake signal is fed in via a `note_wake()` seam the gateway calls on first interaction.
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (T1 LOCKED) · docs/technical/adr/ADR-006-two-tier-proactivity.md.

## Assumptions

- **M6-a** complete: `src/artemis/manifest.py` defines `HookSpec` with `interval_seconds: int | None`, `cron: str | None`, `tier`, `delivery`, `check_ref: Callable[[], HookResult]`, and a `model_validator(mode="after")` enforcing *exactly one of* `interval_seconds`/`cron`. `src/artemis/heartbeat.py` defines `Heartbeat` with `_interval_due`, `_cron_due`, `tick()`, `run_forever`, and per-hook resolved records carrying `next_due` / `last_fired_date`. `src/artemis/proactive/hook_types.py` defines `HookResult`, `Hit`, `TickResult`. → impact: Stop (this spec widens the existing exactly-one-trigger validator to *exactly one of three* and adds a `wake` branch to the due loop — symbol names must match M6-a exactly).
- **X3 runtime-config** complete: `get_runtime_config()` from `artemis.runtime_config` exposes `tasks.morning_digest_fallback_time` (`"08:00"`), `tasks.weekend_review_day` (`5`), `tasks.week_ahead_day` (`6`). The wake fallback time + the day-gate for Sat-wake read from here. → impact: Caution (the fallback-time + day-gate defaults are X3 tunables; the Heartbeat reads the config value at construction, not per-tick — a config reload requires a Heartbeat rebuild, acceptable for daemon-scope config).
- The **wake signal** is an out-of-band fact: "the owner interacted for the first time today". The gateway (M1-b / M1-c surface) calls `heartbeat.note_wake(now_wall)` on the first request of each wall-clock day. M6-wake adds the `note_wake` method + an internal `_wake_date: date | None` latch; it does NOT modify the gateway (the gateway wiring is a one-line call documented as a composition-root requirement, same pattern as M6-a's `on_hits`/`tier1_sink` seams). → impact: Stop (the trigger fires from `note_wake` setting the latch; `tick()` reads the latch).
- A `wake` hook fires **at most once per wall-clock day** — either when `note_wake` is called (wake path) OR at the fallback time if no wake arrived by then (fallback path), whichever comes first; never both. The latch + a `last_fired_date` guard enforce single-fire, mirroring the cron `fire-if-past-and-not-yet-fired` semantics. → impact: Stop (this is the load-bearing single-fire invariant; the test suite asserts it for both paths and the day-gate).
- Off-hardware: fully deterministic — the injectable `wall_clock` + a manual `note_wake()` call + a fake registry, same harness as M6-a's `test_heartbeat_scheduler.py`. No model, no ntfy. → impact: Low.

Simplicity check: considered a separate `WakeScheduler` class running alongside `Heartbeat` — rejected; wake is just a third due-mode on the same per-hook record, sharing the same `last_fired_date` single-fire machinery the cron path already has. Adding a `trigger: Literal["wake"]` branch + a `_wake_date` latch is the minimum. No new dependency; the day-gate is a plain `now.weekday() == gate` check.

## Prerequisites

- Specs complete: **M6-a** (the scheduler this amends), **X3-runtime-config** (fallback time + day-gate tunables).
- Environment: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/manifest.py` | modify | SURGICAL: add `trigger: Literal["interval", "cron", "wake"]` derivation + `wake_fallback_time: str \| None` + `wake_day_gate: int \| None` fields to `HookSpec`; widen the exactly-one-trigger validator to admit the wake form |
| `/Users/artemis-build/artemis/src/artemis/heartbeat.py` | modify | SURGICAL: add `note_wake(now_wall)` + `_wake_date` latch + `_wake_due(rec, now_wall)` branch in `tick()`; read fallback-time/day-gate from X3 at construction |
| `/Users/artemis-build/artemis/tests/test_heartbeat_wake.py` | create | wake-path fire, fallback-path fire, single-fire (never both), day-gate skip/admit, latch reset across days |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Extend `HookSpec` with the wake trigger form** — files: `/Users/artemis-build/artemis/src/artemis/manifest.py` (SURGICAL modify) —

  Add three fields to `HookSpec` (keep all M6-a fields unchanged):
  ```python
  wake: bool = False                      # this hook fires on the daily wake signal (T1)
  wake_fallback_time: str | None = None   # "HH:MM" — fire at this clock if no wake by then (None ⇒ wake-only, no fallback)
  wake_day_gate: int | None = None        # 0=Mon … 6=Sun — fire only on this weekday (None ⇒ every day)
  ```

  Widen the existing `model_validator(mode="after")` (M6-a: "exactly one of interval_seconds/cron"): now **exactly one of** `interval_seconds`, `cron`, or `wake=True` must be the active trigger. Rules:
  - exactly one of `{interval_seconds is not None, cron is not None, wake is True}` is truthy → else raise `ValueError("hook needs exactly one trigger: interval_seconds, cron, or wake")`.
  - if `wake_fallback_time` or `wake_day_gate` is set, `wake` MUST be `True` (raise `ValueError("wake_fallback_time/wake_day_gate require wake=True")`).
  - `wake_fallback_time`, when set, matches `^\d{2}:\d{2}$` valid HH:MM (reuse/replicate the M6-a cron-time parse helper; raise `ValueError` on bad format).
  - `wake_day_gate`, when set, is in `range(0, 7)`.

  The `OWNER_PRIVATE ⇒ tier==1` `ModuleManifest` validator (M6-a) is unchanged and applies to wake hooks too (the Tasks digest hook is Tier-1 on an owner-private module — correct).

  — done when: `uv run mypy --strict src` passes; `HookSpec(name="d", wake=True, wake_fallback_time="08:00", check_ref=<HookResult callable>)` constructs; `HookSpec(name="d", wake=True, interval_seconds=60, ...)` raises (two triggers); `HookSpec(name="d", interval_seconds=60, wake_day_gate=5, ...)` raises (gate without wake); `HookSpec(name="d", wake=True, wake_day_gate=9, ...)` raises.

- [ ] **Task 2: Add the wake latch + due branch to the Heartbeat** — files: `/Users/artemis-build/artemis/src/artemis/heartbeat.py` (SURGICAL modify) —

  Add an instance attribute `self._wake_date: date | None = None` (the wall-clock date for which a wake signal has been observed; `None` ⇒ no wake yet today). Per-hook resolved records already carry `last_fired_date` (cron path) — reuse it for wake single-fire.

  Add:
  ```python
  def note_wake(self, now_wall: datetime) -> None:
      """Record the daily wake signal (first owner interaction of the day). Idempotent within a day.
      The gateway calls this on the first request of each wall-clock day (composition-root wiring)."""
      self._wake_date = now_wall.date()
  ```

  In `tick()`, add a `_wake_due` branch alongside `_interval_due` / `_cron_due` (a hook is dispatched if ANY of its trigger forms is due — but by the Task-1 validator only one form is active per hook):
  ```python
  def _wake_due(self, rec, now_wall: datetime) -> bool:
      """Wake hook fires at most once/day: when a wake signal arrived today, OR at the fallback
      time if set and no wake by then. Day-gated by wake_day_gate. Single-fire via last_fired_date."""
      hook = rec.hook
      today = now_wall.date()
      if rec.last_fired_date == today:
          return False                                  # already fired today (wake OR fallback path)
      if hook.wake_day_gate is not None and now_wall.weekday() != hook.wake_day_gate:
          return False                                  # not this hook's day
      wake_observed = self._wake_date == today
      fallback_reached = (
          hook.wake_fallback_time is not None
          and now_wall >= _today_at(now_wall, hook.wake_fallback_time)  # reuse the cron HH:MM-today helper
      )
      if wake_observed or fallback_reached:
          rec.last_fired_date = today                   # latch single-fire (mirrors _cron_due)
          return True
      return False
  ```
  (`_today_at(now_wall, "HH:MM")` = the M6-a cron evaluator's "today at H:M" datetime builder — factor it out of `_cron_due` if private, or replicate the 2-line parse. Document the reuse.)

  In `tick()`'s due-collection: a record is due if `rec.hook.wake and self._wake_due(rec, now_wall)` (in addition to the existing interval/cron checks). The tier-gate, `check_ref` dispatch, degrade-don't-crash, and `next_due`/`last_fired_date`-advances-on-dispatch semantics from M6-a apply unchanged to wake hooks.

  — done when: `uv run mypy --strict src` passes; with a registry holding one `wake=True` hook, `note_wake(now)` then `tick()` fires it once and a second same-day `tick()` does NOT re-fire; with no `note_wake` but a `wake_fallback_time` past, `tick()` fires it; a `wake_day_gate` mismatch never fires.

- [ ] **Task 3: Tests** — files: `/Users/artemis-build/artemis/tests/test_heartbeat_wake.py` — typed pytest, same fake-clock + fake-registry harness as `test_heartbeat_scheduler.py`.

  - **Wake-path fire:** a `wake=True` hook; `wall_clock` at 07:00 (before any fallback), `tick()` → does NOT fire (no wake yet); call `note_wake(07:05)`; `tick()` → fires once (`tick().hits` has it); a second `tick()` same day → does NOT re-fire.
  - **Fallback-path fire:** a `wake=True, wake_fallback_time="08:00"` hook; no `note_wake`; `tick()` at 07:59 → no fire; `tick()` at 08:01 → fires once; second same-day `tick()` → no re-fire.
  - **Single-fire (never both):** wake at 07:05 then fallback time 08:00 passes → only ONE fire total that day (the wake fire latched `last_fired_date`).
  - **Day-gate skip:** a `wake=True, wake_day_gate=5` (Sat) hook; `wall_clock` on a Wednesday with `note_wake` called → does NOT fire; on a Saturday with `note_wake` → fires.
  - **Latch resets across days:** fire on day 1 (wake path); advance `wall_clock` to day 2; `note_wake(day2)`; `tick()` → fires again (new day). Assert `_wake_date` tracks the latest day.
  - **Tier gate interaction:** a `wake=True` Tier-1 hook on an `OWNER_PRIVATE` module under `FakeKeyProvider(owner_unlocked=False)` → skipped-and-queued (its `check_ref` not called), same as any Tier-1 hook; under unlocked → fires on wake.
  - **Validator round-trips:** constructing the bad `HookSpec` forms from Task 1 raises `ValidationError` (covered here or in a manifest test — assert at least the two-triggers and gate-without-wake cases).

  — done when: `uv run pytest -q tests/test_heartbeat_wake.py` passes AND `uv run mypy --strict src tests/test_heartbeat_wake.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/heartbeat.py` |
| Create | `/Users/artemis-build/artemis/tests/test_heartbeat_wake.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_heartbeat_wake.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_heartbeat_wake.py tests/test_heartbeat_scheduler.py` | Test gate (wake + regression on M6-a scheduler) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/manifest.py`, `src/artemis/heartbeat.py`, `tests/test_heartbeat_wake.py` |
| `git commit` | `"feat: M6-wake-trigger — daily wake hook trigger + fallback + day-gate"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Pure in-process; injected clock + manual note_wake in tests |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No new deps |

## Specialist Context

### Security

- The wake trigger does not change the tier gate: a wake hook on an `OWNER_PRIVATE` module is Tier-1 and is skipped-and-queued while the owner is locked (M6-a invariant unchanged). `note_wake` carries only a date — no owner content, no payload. `tick()` makes zero model/network calls (M6-a property preserved). [apex-security note: confirm `note_wake` only sets a date latch and cannot be used to force-fire a Tier-1 sensitive hook while locked — the tier gate runs AFTER due-evaluation, so a locked Tier-1 wake hook is still skipped.]

### Performance

- The wake check is O(1) per hook per tick (a date comparison + an optional HH:MM parse). No new I/O. The fallback-time `_today_at` parse is cheap; consider caching the parsed time on the record if profiling shows it (premature now).

### Accessibility

(none — no frontend)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/heartbeat.py` | Document `note_wake` as the gateway seam (first-interaction-of-day), the single-fire (wake-or-fallback-never-both) invariant, and the day-gate; note the composition-root wiring requirement (gateway calls `note_wake`) |
| Inline | `src/artemis/manifest.py` | Document the three trigger forms (interval/cron/wake) on the `HookSpec` model |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_heartbeat_wake.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_heartbeat_wake.py tests/test_heartbeat_scheduler.py` → verify: wake-path fires once; fallback-path fires once when no wake; never both same day; day-gate skips/admits; latch resets across days; Tier-1 wake hook skipped while locked; M6-a scheduler regression still green.
- [ ] `uv run python -c "from artemis.heartbeat import Heartbeat; print(hasattr(Heartbeat, 'note_wake'))"` → verify: prints `True`.

## Progress
_(Coding mode writes here — do not edit manually)_
