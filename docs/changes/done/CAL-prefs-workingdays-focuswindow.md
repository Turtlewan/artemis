---
spec: cal-prefs-workingdays-focuswindow
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- AMENDS CAL-a (CalPrefs + find_time / free-gap) per cross-cutting decisions X1 (working_days) and
     X2 (preferred_focus_window). Adds two CalPrefs fields whose defaults are read from the X3
     RuntimeConfig.calendar.* layer. working_days FILTERS find_time + the free-gap hook to working days;
     preferred_focus_window BIASES slot RANKING only — the frozen find_time band-scan algorithm is
     untouched. C5 (hold-tentative-until-approved) is referenced but NOT built here (Wave R
     calendar.create_from_extract owns it). -->

# Spec: CAL-prefs — `working_days` + `preferred_focus_window` on `CalPrefs` (X1/X2)

**Identity:** Adds `working_days: tuple[int, ...]` and `preferred_focus_window: tuple[str, str]` to the canonical `CalPrefs` dataclass; applies a working-days filter to `find_time` results + the free-gap hook so neither proposes slots on non-working days (X1); and adds a `rank_slots_by_focus_window` post-pass that biases the `find_time` slot ranking toward the morning focus window without altering the frozen band-scan algorithm (X2). Defaults are sourced from the X3 `RuntimeConfig.calendar.*` layer.
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (X1, X2 LOCKED) · docs/technical/contracts.md Seam 4 (CalPrefs canonical) · docs/technical/adr/ADR-022 (model/runtime) · docs/changes/X3-runtime-config.md.

<!-- Split rule: ONE logical phase — two additive CalPrefs fields + one filter pass + one ranking helper,
     across the existing CalPrefs/find_time/free-gap files. Pure amendment; no new module surface, no new
     store. C5 overlay change is explicitly out of scope (Wave R). Within the 3-file spirit. -->

## Assumptions

- **CAL-a** complete: `@dataclass(frozen=True) class CalPrefs` exists at `src/artemis/modules/calendar/preferences.py` with the locked fields `working_hours_start`, `working_hours_end`, `timezone`, `default_write_calendar`, `buffer_minutes`, `no_meeting_before`, `no_meeting_after`, `default_reminder_minutes`, `focus_block_duration_minutes`, `sync_window_months_past`, `sync_window_months_future`, `owner_email`. All have defaults so `CalPrefs()` is valid. The two new fields are ADDED to this dataclass; existing field names are untouched (no collision — neither `working_days` nor `preferred_focus_window` exists today). → impact: Stop (verify the exact field set before editing; the new fields must not shadow any existing one).
- **CAL-a** `FindTimeEngine` exists at `src/artemis/modules/calendar/read_tools.py`, constructed with `(prefs: CalPrefs)`, exposing the **frozen** pure helper `def find_slots(self, busy_blocks, window_start, window_end, duration_minutes, *, buffer_minutes=None) -> list[FreeSlot]` (band-scan over working-hours/no-meeting bands, ≤10 slots, earliest-first). `find_time_tool` and `find_time_with_attendees_tool` call `find_slots`. `FreeSlot` has `start_dt: str`, `end_dt: str`, `duration_minutes: int` (ISO-8601 strings). → impact: Stop (X2 biasing is a post-pass over `find_slots` output — the band-scan algorithm body is NOT modified; only a filter + a re-rank wrap its result).
- **CAL-c** owns the free-gap hook (C6: free-gap propose-only, 1/day, morning). This spec adds the working-days skip to whatever surface CAL-c's free-gap check enumerates candidate days on. If CAL-c is not yet built, this spec's free-gap delta folds into CAL-c's build (the working-days filter is applied at the day-enumeration step). The working-days filter belongs in the shared day-enumeration logic so both `find_time` and the free-gap hook honour it. → impact: Caution (the free-gap edit is conditional on CAL-c's existence; if CAL-c is absent, record the delta as a forward-requirement on CAL-c and build only the CalPrefs fields + the find_time filter/rank here).
- **X3 runtime-config** complete: `get_runtime_config()` from `artemis.runtime_config` exposes `RuntimeConfig.calendar.working_days: tuple[int, ...]` (default `(0,1,2,3,4)` Mon–Fri, 0=Mon…6=Sun) and `RuntimeConfig.calendar.preferred_focus_window: tuple[str, str]` (default `("09:00", "12:00")`, validated HH:MM with start < end). The CalPrefs defaults for the two new fields are sourced from X3 at the composition root (where `CalPrefs` is constructed / loaded), NOT hardcoded in the dataclass — see Task 1 note. → impact: Stop (the dataclass field defaults mirror the X3 defaults so an off-hardware `CalPrefs()` is still valid; the composition root overrides them from X3 when wiring the real prefs).
- `working_days` is a weekday-int tuple (`datetime.weekday()` semantics: Monday=0 … Sunday=6). A slot is on a working day iff `slot_start.weekday() in working_days`. The frozen `find_slots` band-scan already iterates per calendar day; the working-days filter drops slots whose day is non-working (applied as a filter over the returned `FreeSlot` list, OR as a per-day skip inside the day-enumeration — see Task 2 for the chosen, lower-risk approach). → impact: Stop.
- `preferred_focus_window` biases RANKING only. The ranking rule (X2 "morning bias, earliest-fallback"): among the working-day-filtered slots, prefer the earliest slot whose `start` time-of-day falls within `[focus_start, focus_end)`; if at least one slot is within the window, return the within-window slots first (earliest-first) then the remaining slots (earliest-first); if NO slot is within the window, fall back to the plain earliest-first order (unchanged). The band-scan algorithm and its slot boundaries are NOT changed — only the order of the returned list is re-sorted. → impact: Stop (this is the load-bearing "ranking, not algorithm" invariant; tests assert the band-scan output set is identical pre/post and only the order differs).
- Off-hardware: deterministic — synthetic busy blocks + a fixed `CalPrefs`, same fakes harness as CAL-a's `test_calendar_read.py`. No model, no Google. → impact: Low.

Simplicity check: considered threading `working_days` + `preferred_focus_window` into the `find_slots` band-scan body — rejected; that mutates the frozen algorithm and entangles X1/X2 with the band math. The minimal, lowest-risk change is two additive dataclass fields + a thin filter (`drop non-working-day slots`) + a thin re-rank (`rank_slots_by_focus_window`) applied to `find_slots`'s output. No new types beyond a module-level helper function. The free-gap skip reuses the same `working_days` membership check.

## Prerequisites

- Specs complete: **CAL-a** (`CalPrefs`, `FindTimeEngine.find_slots`, `find_time_tool`). **X3-runtime-config** (`RuntimeConfig.calendar.*`). **CAL-c** (free-gap hook — conditional; if absent, the free-gap delta is a forward-requirement).
- Environment: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/preferences.py` | modify | add `working_days: tuple[int, ...]` + `preferred_focus_window: tuple[str, str]` to `CalPrefs` (with X3-mirroring defaults); ensure `load`/`save`/`update` round-trip the new fields (JSON list→tuple coercion) |
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/read_tools.py` | modify | add `_is_working_day(dt, working_days)` + `rank_slots_by_focus_window(slots, focus_window)` helpers; apply working-days filter + focus-window rank to `find_time_tool` / `find_time_with_attendees_tool` output (NOT inside `find_slots`) |
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/hooks.py` | modify (conditional) | free-gap hook day-enumeration skips non-working days (only if CAL-c's `hooks.py` exists; else record as forward-requirement) |
| `/Users/artemis-build/artemis/tests/test_calendar_prefs_workingdays.py` | create | CalPrefs round-trip of new fields; working-days filter; focus-window ranking (set-identical, order-biased); free-gap working-days skip (if applicable) |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Add the two fields to `CalPrefs`** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/preferences.py` (modify) —

  Add to the `CalPrefs` frozen dataclass (after `owner_email`, keeping all existing fields unchanged):
  ```python
  working_days: tuple[int, ...] = (0, 1, 2, 3, 4)          # X1 — Mon–Fri (0=Mon … 6=Sun); mirrors RuntimeConfig.calendar.working_days
  preferred_focus_window: tuple[str, str] = ("09:00", "12:00")  # X2 — morning bias, earliest-fallback; mirrors RuntimeConfig.calendar.preferred_focus_window
  ```

  **Composition-root sourcing note (inline + docstring):** the dataclass defaults mirror the X3 defaults so `CalPrefs()` stays valid off-hardware. At the composition root where the real `CalPrefs` is constructed/loaded, override these two fields from `get_runtime_config().calendar` (`working_days`, `preferred_focus_window`) — e.g. `dataclasses.replace(loaded_prefs, working_days=cfg.calendar.working_days, preferred_focus_window=cfg.calendar.preferred_focus_window)`. Document this wiring requirement; do NOT import `runtime_config` inside `preferences.py` (keep the store free of config-layer coupling — the override happens at composition).

  **`PreferencesStore.load` JSON coercion:** the stored JSON serialises tuples as lists. `CalPrefs(**filtered)` must coerce `working_days` (a JSON list of ints) and `preferred_focus_window` (a JSON list of 2 strings) back to tuples. Since the dataclass field type is `tuple[...]`, after `json.loads` wrap: `working_days=tuple(data["working_days"])`, `preferred_focus_window=tuple(data["preferred_focus_window"])` in the field-filter construction. `save` (via `dataclasses.asdict`) serialises tuples to JSON lists — fine. `update(**kwargs)` accepts the two new field names (the existing `ValueError` on unknown field still applies to genuinely unknown keys).

  **Validation:** `update`/construction does not need range validation here (X3 already validates `working_days ⊂ range(0,7)` and the focus-window HH:MM/order at the config layer; CalPrefs trusts X3-sourced values). Add a light docstring note that out-of-range values are an X3-layer concern.

  — done when: `uv run mypy --strict src` passes; `CalPrefs()` has `working_days == (0,1,2,3,4)` and `preferred_focus_window == ("09:00","12:00")`; `PreferencesStore.save(CalPrefs(working_days=(0,1,2,3), preferred_focus_window=("08:00","11:00")))` then `load()` round-trips both as tuples (off-hardware via the dict-backed `FakePreferencesStore` shim from CAL-a tests); `update(working_days=(0,1,2,3,4,5))` returns prefs with the Saturday added.

- [ ] **Task 2: Working-days filter + focus-window ranking helpers** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/read_tools.py` (modify) —

  Add two module-level pure helpers (NOT methods of `FindTimeEngine`; the frozen `find_slots` body is untouched):

  ```python
  def _is_working_day(slot_start_iso: str, working_days: tuple[int, ...], tz: str) -> bool:
      """True if the slot's start date falls on a configured working day (X1).
      Parses the ISO-8601 start in the prefs timezone; compares datetime.weekday() (Mon=0)."""
      dt = _parse_iso_local(slot_start_iso, tz)   # reuse CAL-a's ISO/timezone parse helper
      return dt.weekday() in working_days

  def filter_working_days(slots: list[FreeSlot], working_days: tuple[int, ...], tz: str) -> list[FreeSlot]:
      """Drop slots whose start is on a non-working day (X1). Order preserved."""
      return [s for s in slots if _is_working_day(s.start_dt, working_days, tz)]

  def rank_slots_by_focus_window(slots: list[FreeSlot], focus_window: tuple[str, str], tz: str) -> list[FreeSlot]:
      """X2 morning-bias ranking — RANKING ONLY, never alters slot boundaries.
      Partition the (already earliest-first) slots into within-window and outside-window by
      time-of-day of start; return within-window first (earliest-first), then the rest
      (earliest-first). If no slot is within the window, returns the input unchanged
      (earliest-fallback)."""
      fstart, fend = focus_window  # "HH:MM" strings
      def in_window(s: FreeSlot) -> bool:
          tod = _time_of_day(s.start_dt, tz)        # "HH:MM" of the slot start
          return fstart <= tod < fend               # lexical HH:MM compare is valid for zero-padded times
      within = [s for s in slots if in_window(s)]
      outside = [s for s in slots if not in_window(s)]
      return within + outside if within else slots
  ```
  (`_parse_iso_local` / `_time_of_day` reuse CAL-a's existing ISO-8601 + `prefs.timezone` parsing utilities in `read_tools.py`/`cache.py`; if a `_time_of_day` helper does not exist, add a 2-line one that formats the parsed local datetime as `"%H:%M"`. Document the reuse.)

  **Apply to the find-time tools** (post-pass over `find_slots` output — the band-scan call is unchanged):
  - In `find_time_tool`: after `slots = FindTimeEngine(prefs).find_slots(...)`, apply `slots = filter_working_days(slots, prefs.working_days, prefs.timezone)` then `slots = rank_slots_by_focus_window(slots, prefs.preferred_focus_window, prefs.timezone)`; cap to 10 (already ≤10 from `find_slots`, but re-cap defensively after filtering if filtering could expose more — it cannot grow the set, so the cap is a no-op safeguard). Return `FindTimeResult(slots=slots)`.
  - In `find_time_with_attendees_tool`: apply the SAME working-days filter (a non-working-day mutual slot is still undesirable). The focus-window rank is also applied (morning bias holds for meetings too). Document that attendee scheduling honours the owner's working days + focus bias.

  **Invariant (inline comment):** `# X2 is RANKING ONLY: rank_slots_by_focus_window never changes a slot's start/end/duration; it only reorders. The frozen find_slots band-scan is not modified. filter_working_days only removes whole slots (X1), never edits one.`

  — done when: `uv run mypy --strict src` passes; `filter_working_days` drops a Saturday slot when `working_days=(0,1,2,3,4)`; `rank_slots_by_focus_window` with one 10:00 slot + one 14:00 slot and `focus_window=("09:00","12:00")` returns the 10:00 slot first; with two afternoon slots (none in window) returns them unchanged (earliest-first); the returned slot OBJECTS are identical to `find_slots`'s output (same `start_dt`/`end_dt`/`duration_minutes`) — only order/membership changes.

- [ ] **Task 3 (conditional): Free-gap hook skips non-working days** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/hooks.py` (modify, ONLY if CAL-c's `hooks.py` exists) —

  In CAL-c's free-gap `check_ref` (C6: propose a free morning gap, 1/day): where it enumerates the candidate day(s) to check for a free gap, skip any day whose `weekday() not in prefs.working_days`. Concretely: the free-gap check that today (or the target day) has an open morning slot returns `HookResult.miss()` immediately if `target_day.weekday() not in prefs.working_days` (no weekend free-gap nudges — X1).

  If CAL-c's `hooks.py` does NOT yet exist at build time: do NOT create it here. Record this as a **forward-requirement** in the spec output and in CAL-c's prerequisites — CAL-c's free-gap `check_ref` must gate on `prefs.working_days`. (The `working_days` field added in Task 1 is the contract CAL-c binds to.)

  — done when (if CAL-c exists): `uv run mypy --strict src` passes; the free-gap `check_ref` returns `HookResult.miss()` on a Saturday when `working_days=(0,1,2,3,4)` and a hit (open gap) on a Wednesday; (if CAL-c absent): the forward-requirement is recorded and this task is marked N/A.

- [ ] **Task 4: Tests** — files: `/Users/artemis-build/artemis/tests/test_calendar_prefs_workingdays.py` — typed pytest, CAL-a fakes harness (`FakePreferencesStore`, synthetic busy blocks, fixed `CalPrefs`). Find-time tool tests are `async def` (ADR-016: `find_time_tool` is an async `callable_ref`) and `await` the call; the helpers (`filter_working_days`/`rank_slots_by_focus_window`) are sync.

  - **CalPrefs round-trip:** `CalPrefs()` defaults are `working_days=(0,1,2,3,4)`, `preferred_focus_window=("09:00","12:00")`; `FakePreferencesStore` (or real-shim) `save` + `load` round-trips a custom `working_days=(0,1,2,3)` + `preferred_focus_window=("08:00","11:00")` as TUPLES (assert `isinstance(..., tuple)` after load — JSON list coercion).
  - **`update` accepts new fields:** `store.update(working_days=(0,1,2,3,4,5))` returns prefs with Saturday included; `store.update(nonsense=1)` still raises `ValueError`.
  - **Working-days filter:** `filter_working_days([<Fri slot>, <Sat slot>, <Mon slot>], (0,1,2,3,4), "UTC")` returns only the Fri and Mon slots (Sat dropped); with `working_days=(0,1,2,3,4,5,6)` returns all three.
  - **Focus-window ranking — within-window first:** slots `[10:00, 14:00]` (earliest-first), `focus_window=("09:00","12:00")` → ranked `[10:00, 14:00]` (10:00 within window, stays first); slots `[14:00, 10:00]` should never occur (find_slots is earliest-first) but assert the helper still returns the within-window slot first when given `[08:00(out), 10:00(in), 14:00(out)]` → `[10:00, 08:00, 14:00]` (within first, then the rest earliest-first).
  - **Focus-window ranking — earliest-fallback:** slots `[13:00, 15:00]` (none within `("09:00","12:00")`) → returned unchanged `[13:00, 15:00]` (earliest-first preserved).
  - **Set-identity invariant:** the multiset of `(start_dt,end_dt,duration_minutes)` tuples is identical before and after `rank_slots_by_focus_window` (only order changes); after `filter_working_days` it is a subset (no slot edited).
  - **find_time_tool end-to-end:** `await find_time_tool(FindTimeArgs(duration_minutes=60, window=<a Fri–Mon span>), store=fake_cache, prefs=CalPrefs(working_days=(0,1,2,3,4), preferred_focus_window=("09:00","12:00")))` over busy blocks that leave a Sat morning gap and a Mon morning gap → the Sat gap is absent from `result.slots`; the Mon morning slot ranks ahead of any Mon afternoon slot.
  - **(conditional) Free-gap working-days skip:** if CAL-c exists, the free-gap `check_ref` misses on Saturday, hits on Wednesday (with an open morning gap).

  — done when: `uv run pytest -q tests/test_calendar_prefs_workingdays.py` passes AND `uv run mypy --strict src tests/test_calendar_prefs_workingdays.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 5 (GATED — on-hardware):** With the real `PreferencesStore` under the broker-mounted vault: `save`/`load` round-trips `working_days` + `preferred_focus_window` under real SQLCipher; the composition root sources both from `get_runtime_config().calendar` and `find_time` over the real event cache excludes non-working-day slots and ranks the focus window first. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/calendar/preferences.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/calendar/read_tools.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/calendar/hooks.py` (conditional — only if CAL-c exists) |
| Create | `/Users/artemis-build/artemis/tests/test_calendar_prefs_workingdays.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_calendar_prefs_workingdays.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_calendar_prefs_workingdays.py tests/test_calendar_read.py` | Test gate + CAL-a regression |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/calendar/preferences.py`, `src/artemis/modules/calendar/read_tools.py`, `src/artemis/modules/calendar/hooks.py` (if modified), `tests/test_calendar_prefs_workingdays.py` |
| `git commit` | `"feat: CalPrefs working_days + preferred_focus_window (X1/X2) — find_time filter + focus-window rank"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | Fakes only; real Google round-trips are CAL-a's GATED tail |

## Specialist Context

### Security

- No new data surface; two additive preference scalars on an already-encrypted owner-private store. `working_days`/`preferred_focus_window` are owner-set tunables, not sensitive. They are sourced from the X3 `policy.json` (owner-authored, trusted, local). No injection surface (integer tuple + two HH:MM strings, validated at the X3 layer). [apex-security note: confirm the focus-window strings are never interpolated into SQL or an LLM prompt — they only drive a lexical HH:MM comparison in the ranking helper.]

### Performance

- `filter_working_days` + `rank_slots_by_focus_window` are O(n) over ≤10 slots — negligible. The frozen `find_slots` band-scan is unchanged (its complexity is unaffected). The free-gap working-days skip short-circuits the check on non-working days (cheaper, not costlier).

### Accessibility

(none — no frontend; the client settings UI that edits `working_days`/`preferred_focus_window` via policy.json is Wave U)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/calendar/preferences.py` | Document the two new fields (X1/X2), the X3-sourced default + composition-root override, and the JSON list→tuple coercion in `load` |
| Inline | `src/artemis/modules/calendar/read_tools.py` | Document the "ranking only, never alters slot boundaries" invariant on `rank_slots_by_focus_window` and the working-days filter; note the frozen `find_slots` band-scan is untouched |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_calendar_prefs_workingdays.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_calendar_prefs_workingdays.py tests/test_calendar_read.py` → verify: CalPrefs new-field round-trip (tuples); working-days filter drops non-working-day slots; focus-window rank puts within-window slots first and falls back to earliest order when none qualify; set-identity invariant (rank reorders only, filter subsets only); `find_time_tool` excludes non-working days + ranks focus window first; CAL-a read tests still green (no regression).
- [ ] `uv run python -c "from artemis.modules.calendar.preferences import CalPrefs; p=CalPrefs(); print(p.working_days, p.preferred_focus_window)"` → verify: prints `(0, 1, 2, 3, 4) ('09:00', '12:00')`.
- [ ] (GATED, on Mini) real SQLCipher round-trip of both fields + composition-root sources them from X3 + find_time honours working days/focus window on the real cache → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
