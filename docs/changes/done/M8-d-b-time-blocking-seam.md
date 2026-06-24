---
spec: m8-d-b-time-blocking-seam
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seams 3, 5, 6) + m8-productivity.md BLOCKs B1, B2, F7 -->
<!-- Seam 3: stage() uses front-door fq id; _execute twins registered per tool — no gated tools in M8-d-b
     (block_focus_time is AUTO via CAL-b classifier rule 2; cancel_event for self-only block is AUTO).
     No staging service calls needed here; no change required for Seam 3.
     Seam 5: check_ref sync, payload ids+counts — no hooks in M8-d-b; no change required.
     Seam 6: no GOAL/PERSON entity linking in M8-d-b; no change required.
     B1 fix: manifest signature stated cumulatively; tool count is relative; build order pinned.
     B2 fix: link-clear uses clear_task_schedule_link (NOT update_task with None sentinels).
     F7 fix: Assumption text uses CalPrefs (not CalendarPrefs). -->

# Spec: M8-d-b — Calendar time-blocking seam: `calendar.schedule_task` primitive + `task.schedule` tool + Task↔Event link

**Identity:** Adds a `calendar.schedule_task` primitive to the Calendar module (auto, self-only focus block for a specific task), the `task.schedule` tool to the Productivity module (calls the primitive, writes the Task↔Event link), and link-aware behaviour on `task.complete` (clears stale link field on completion of a time-blocked task).
→ why: see docs/technical/modules/productivity.md §C levels 2+3 · docs/technical/adr/ADR-011-spoke-source-of-truth.md (self-only writes auto, no gating)

<!-- TWO logical phases: Phase 1 — `calendar.schedule_task` primitive (additive to the Calendar module).
     Phase 2 — `task.schedule` tool + link-write + completion-loop behaviour (additive to the Productivity module).
     Phase 2 depends on Phase 1 being importable; both can be built in one coding session. Touches exactly
     4 source files (2 new, 2 modify) + 1 test file — within the 3-file spirit; split not warranted. -->

## Assumptions

- **M8-d-a** is complete: `ProductivityRepository.update_task(id, *, calendar_event_id=None, scheduled_block=None)` exists; `task.complete` tool calls `repository.complete_task(id)` (recurrence-aware); `ProductivityStore` is importable from `artemis.modules.productivity`. → impact: Stop (the link-write path calls `update_task`; verify exact method signature before executing Task 3).
- **CAL-a** is complete: `FindTimeEngine`, `find_time_tool`, `CalPrefs` (`focus_block_duration_minutes`, `default_write_calendar`, `owner_email`), `EventCacheStore`, `FakeCalendarClient` are all importable from `artemis.modules.calendar`. (F7 fix: `CalPrefs` is the canonical name per contracts.md Seam 4 / CAL-a Task 1; `CalendarPrefs` is a stale alias.) → impact: Stop.
- **CAL-b** is complete: `CalendarWriteTools.block_focus_time(BlockFocusTimeArgs)` exists and returns `WriteResult(event_id, summary, status, tool_name)`; `gating.classify("block_focus_time", [], owner_email)` → `AUTO` (confirmed by CAL-b spec Task 2 rule 2 — `block_focus_time` is always auto); `ActivityLog` is present. → impact: Stop.
- `CalendarWriteTools` is constructed with `(client, cache, prefs, staging, activity_log)` as in CAL-b Task 3. It is a normal (non-final) class — confirmed by CAL-b Task 3 which defines `class CalendarWriteTools` with no `@final` decorator or sealing mechanism. The `calendar.schedule_task` primitive is a NEW module-level function `schedule_task(args, *, write_tools, find_time_fn, prefs)` (NOT a method of `CalendarWriteTools`) — it calls `write_tools.block_focus_time(BlockFocusTimeArgs(...))` via the public method. The CAL-b classifier hard-codes `block_focus_time` → `AUTO` (rule 2), so this call always executes write-through. → impact: Caution (verify exact `CalendarWriteTools` constructor arg names match CAL-b Task 3 before executing Task 1).
- `BlockFocusTimeArgs.title` is a settable string field (not a hardcoded constant). Confirmed by CAL-b Task 1: `BlockFocusTimeArgs(start_datetime: str, end_datetime: str, title: str = "Focus time", calendar_id: str | None = None)`. The `calendar.schedule_task` primitive passes `title=f"[Task] {task_title}"` to distinguish task-focus-blocks from generic focus-time blocks. → impact: Low.
- `WriteResult.event_id` is the created Google Calendar event id (confirmed by CAL-b Task 1). This is what is stored as `task.calendar_event_id`. → impact: Stop.
- `find_time_tool` returns a `FindTimeResult(slots: list[FreeSlot])` where `FreeSlot` has `start_dt: str` and `end_dt: str` (ISO-8601). The primitive picks `slots[0]` (earliest). If `slots` is empty, `calendar.schedule_task` returns a typed `NoSlotFoundError` — it does NOT raise. → impact: Stop (the `task.schedule` tool must surface this to the brain as an informative result, not a crash).
- `CalPrefs.focus_block_duration_minutes` (default 90) is used as the slot duration when no `window` override is provided. When a `window` is passed, the primitive uses the window's duration (end − start) as the requested `duration_minutes`. → impact: Low.
- `task.complete` in M8-d-a sets `status="done"`, `completed_at=now`, and spawns the recurrence next-instance. The link-aware behaviour added here clears `calendar_event_id` and `scheduled_block` on the COMPLETED task (the link is stale once done — the event already happened). The SPAWNED next-instance starts with NULL `calendar_event_id`/`scheduled_block` (it needs its own scheduling). → impact: Caution (confirm that `complete_task` in `repository.py` is the correct insertion point and that it returns the completed task dict before exit — M8-d-a Task 2 confirms it does).
- Off-hardware: `FakeCalendarClient` (from CAL-a) + `ProductivityStore` over a temp SQLCipher (or plain sqlite fallback per M8-d-a pattern) + `FakeKeyProvider`. No real Google calls. Real write-through is GATED on-hardware. → impact: Stop (CI must pass without credentials).
- Module package paths: `src/artemis/modules/calendar/` and `src/artemis/modules/productivity/` are the locked conventions (both confirmed by CAL-a and M8-d-a). → impact: Stop.
- `ActionRisk.WRITE` is the correct risk for `calendar.schedule_task` — it calls `block_focus_time` which is `ActionRisk.WRITE` and always `AUTO`. No `HIGH_STAKES` needed (self-only, no attendees, no gating). → impact: Low.

Simplicity check: considered adding `calendar.schedule_task` as a method on `CalendarWriteTools` directly — rejected as it would require modifying CAL-b's closed spec. Considered adding `schedule_task` as a standalone function rather than a thin class — both work; chose a module-level function `schedule_task(args, *, write_tools, find_time_fn, prefs)` for maximum testability and to match the CAL-a `read_tools.py` function-over-dependencies pattern. No new data models beyond what M8-d-a already defined.

## Prerequisites

**Build order (B1 fix): a → b → c1 → c2.** This spec (b) requires M8-d-a complete. M8-d-c1 requires M8-d-b complete. M8-d-c2 requires M8-d-c1 complete.

- Specs complete: **M8-d-a** (repository + `update_task` + `clear_task_schedule_link`; `complete_task`; `ProductivityStore`; `task.complete` tool), **CAL-a** (`find_time_tool`, `FakeCalendarClient`, `CalPrefs`, `EventCacheStore`), **CAL-b** (`CalendarWriteTools.block_focus_time`, `BlockFocusTimeArgs`, `WriteResult`, `ActivityLog`, `GateDecision`).
- Environment setup: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/schedule_task.py` | create | `calendar.schedule_task` primitive: args/return schemas + `schedule_task()` function |
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` | modify | add `calendar.schedule_task` ToolSpec (additive — one new entry) |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` | modify | add `task_schedule` callable + `task_complete` link-clear behaviour |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` | modify | add `task.schedule` ToolSpec to the manifest (brings total tools from 30 → 31) |
| `/Users/artemis-build/artemis/tests/test_time_blocking_seam.py` | create | off-hardware tests: primitive happy-path, no-slot, link-write round-trip, completion link-clear |

## Tasks

### Phase 1 — `calendar.schedule_task` primitive

- [ ] **Task 1: Define args/return schemas + `schedule_task` function** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/schedule_task.py` —

  **Pydantic schemas** (all `model_config = ConfigDict(frozen=True)`):

  ```python
  class ScheduleTaskArgs(BaseModel):
      model_config = ConfigDict(frozen=True)
      task_id: str                     # the Productivity task id (for logging / link-back)
      task_title: str                  # used as the focus-block event title suffix
      estimate_minutes: int | None = None  # caller-supplied; overrides prefs.focus_block_duration_minutes
      window_start: str | None = None  # ISO-8601; if None, use now → now+7d
      window_end: str | None = None    # ISO-8601; if None, use now → now+7d
      calendar_id: str | None = None   # if None, write_tools uses prefs.default_write_calendar

  class ScheduledBlock(BaseModel):
      model_config = ConfigDict(frozen=True)
      event_id: str        # Google Calendar event id
      start_dt: str        # ISO-8601 start of the created block
      end_dt: str          # ISO-8601 end of the created block
      calendar_id: str     # resolved calendar id

  class ScheduleTaskResult(BaseModel):
      model_config = ConfigDict(frozen=True)
      scheduled: ScheduledBlock | None   # None if no slot was found
      message: str                        # human-readable outcome for the brain
  ```

  **`schedule_task` function signature** (ADR-016: this is the bound `calendar.schedule_task` `callable_ref` via `functools.partial`, so it is `async def`; it `await`s `write_tools.block_focus_time` — the `_execute` write twin does Google API I/O):

  ```python
  async def schedule_task(
      args: ScheduleTaskArgs,
      *,
      write_tools: CalendarWriteTools,      # CAL-b: for block_focus_time
      find_time_fn: Callable[[FindTimeArgs], Awaitable[FindTimeResult]],  # CAL-a: find_time_tool bound with store+prefs (async callable_ref — ADR-016)
      prefs: CalPrefs,                      # CAL-a canonical name (not CalendarPrefs — F7)
  ) -> ScheduleTaskResult:
  ```

  **Implementation steps** (in order):

  1. Resolve `duration_minutes`:
     - If `args.estimate_minutes` is not None → `duration_minutes = args.estimate_minutes`
     - Else → `duration_minutes = prefs.focus_block_duration_minutes`  (default 90)

  2. Resolve search window:
     - If `args.window_start` and `args.window_end` are both provided → use as-is.
     - If either is None → use `datetime.now(timezone.utc)` as `now`; `window_start = now.isoformat()`, `window_end = (now + timedelta(days=7)).isoformat()` (timezone-aware; yields `+00:00` suffix — do NOT append `"Z"` separately; consistent with the `now_iso()` helper defined in M8-d-a).

  3. Call `result = await find_time_fn(FindTimeArgs(duration_minutes=duration_minutes, window=Window(start=window_start, end=window_end)))` (ADR-016: `find_time_fn` is an async `callable_ref` — `await` it).

  4. If `result.slots` is empty:
     - Return `ScheduleTaskResult(scheduled=None, message=f"No open slot found for '{args.task_title}' in the requested window.")`.

  5. Pick `slot = result.slots[0]` (earliest).

  6. Build the focus-block title: `title = f"[Task] {args.task_title}"`.

  7. Call `write_result = await write_tools.block_focus_time(BlockFocusTimeArgs(start_datetime=slot.start_dt, end_datetime=slot.end_dt, title=title, calendar_id=args.calendar_id))` (ADR-016: `block_focus_time` is an async tool callable performing Google API I/O — `await` it).
     - `block_focus_time` is always `AUTO` per CAL-b classifier (rule 2: `block_focus_time` → unconditional `AUTO`).
     - Returns `WriteResult` with `event_id`, `status="executed"`.
     - On `CalendarWriteError` → re-raise (do NOT swallow; the caller logs).

  8. Resolve the `calendar_id` that was actually used: if `args.calendar_id` is not None use it, else use `prefs.default_write_calendar`.

  9. Return `ScheduleTaskResult(scheduled=ScheduledBlock(event_id=write_result.event_id, start_dt=slot.start_dt, end_dt=slot.end_dt, calendar_id=resolved_calendar_id), message=f"Scheduled '{args.task_title}' on {slot.start_dt} → {slot.end_dt}.")`.

  Imports required: `from artemis.modules.calendar.write_tools import CalendarWriteTools, BlockFocusTimeArgs, WriteResult, CalendarWriteError`; `from artemis.modules.calendar.read_tools import FindTimeArgs, FindTimeResult, FreeSlot, Window`; `from artemis.modules.calendar.preferences import CalPrefs`; standard `datetime`, `timedelta`; `Callable`, `Awaitable` from `collections.abc` (ADR-016 async `find_time_fn` type).

  — done when: `uv run mypy --strict src` passes; `await schedule_task(...)` (async test) with a `FakeCalendarClient` + mocked async `find_time_fn` returning one slot → returns `ScheduleTaskResult` with `scheduled.event_id` set; no-slot case returns `scheduled=None`; `CalendarWriteError` from `block_focus_time` propagates.

- [ ] **Task 2: Add `calendar.schedule_task` ToolSpec to the Calendar manifest** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` (modify, additive only) —

  Add one `ToolSpec` entry to the manifest's `tools` list (after the existing entries):

  ```python
  ToolSpec(
      name="calendar.schedule_task",
      description=(
          "Find the earliest open focus-block slot for a task and create a self-only "
          "focus-block calendar event. Returns the created event_id and block times, "
          "or a message if no slot is available. Always auto (self-only, no attendees)."
      ),
      args_schema=ScheduleTaskArgs,
      return_schema=ScheduleTaskResult,
      callable_ref=<bound method / partial — see wiring note below>,
      action_risk=ActionRisk.WRITE,
  )
  ```

  **Wiring note:** `schedule_task` needs `write_tools`, `find_time_fn`, and `prefs` injected. In `make_calendar_manifest` (or its equivalent factory), add a `schedule_task_fn` parameter (an async `Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]]` — ADR-016: `callable_ref` is async; `functools.partial` over an `async def` is itself a coroutine function) constructed by the composition root using `functools.partial(schedule_task, write_tools=wt, find_time_fn=ft, prefs=p)`. Pass it as `callable_ref`. The manifest factory signature change is additive: `make_calendar_manifest(tools: CalendarTools, schedule_task_fn: Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]]) -> ModuleManifest`. Update `__init__.py` re-export of `make_calendar_manifest` accordingly.

  — done when: `uv run mypy --strict src` passes; `from artemis.modules.calendar.manifest import make_calendar_manifest` succeeds; the new ToolSpec appears in the tools list with `name="calendar.schedule_task"` and `action_risk=ActionRisk.WRITE`.

### Phase 2 — `task.schedule` tool + link-write + completion-loop

- [ ] **Task 3: Add `task_schedule` callable + link-clear in `task_complete`** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` (modify, additive) —

  **3a. New `task_schedule` callable:**

  Add the following args/return models and callable function to `tools.py`:

  ```python
  class TaskScheduleArgs(BaseModel):
      model_config = ConfigDict(frozen=True)
      task_id: str
      window_start: str | None = None   # ISO-8601; forwarded to calendar.schedule_task
      window_end: str | None = None

  class TaskScheduleResult(BaseModel):
      model_config = ConfigDict(frozen=True)
      task_id: str
      event_id: str | None          # None if no slot found
      scheduled_block: str | None   # ISO-8601 start_dt of the created block, or None
      message: str
  ```

  Callable function `async def task_schedule(args: TaskScheduleArgs) -> TaskScheduleResult` (ADR-016: every `ToolSpec.callable_ref` is uniformly `async def`; it `await`s the async `schedule_fn` and the async `write_tools.cancel_event`. The `store.*` SQLCipher calls stay sync inside the async body):

  ```python
  async def task_schedule(args: TaskScheduleArgs) -> TaskScheduleResult:
      store = _get_store()               # raises RuntimeError if not initialised
      schedule_fn = _get_schedule_fn()   # raises RuntimeError if not initialised (see wiring note)
      write_tools = _get_write_tools()   # raises RuntimeError if not initialised (see wiring note)

      task = store.get_task(args.task_id)   # sync SQLCipher read
      if task is None:
          return TaskScheduleResult(task_id=args.task_id, event_id=None, scheduled_block=None,
                                    message=f"Task {args.task_id} not found.")

      # Auto-cancel old focus-block on re-schedule — prevents orphaned "Task: X" events.
      # cancel_event on a self-only block is AUTO (no attendees → classifier rule 4 → AUTO).
      old_event_id = task.get("calendar_event_id")
      if old_event_id:
          await write_tools.cancel_event(CancelEventArgs(event_id=old_event_id, recurrence_scope="THIS_EVENT"))  # ADR-016: async Google-I/O tool — await

      result: ScheduleTaskResult = await schedule_fn(ScheduleTaskArgs(   # ADR-016: schedule_fn is an async callable_ref — await
          task_id=args.task_id,
          task_title=task["title"],
          estimate_minutes=task.get("estimate_minutes"),
          window_start=args.window_start,
          window_end=args.window_end,
      ))

      if result.scheduled is None:
          return TaskScheduleResult(task_id=args.task_id, event_id=None, scheduled_block=None,
                                    message=result.message)

      # Write the Task↔Event link
      store.update_task(
          args.task_id,
          calendar_event_id=result.scheduled.event_id,
          scheduled_block=result.scheduled.start_dt,
      )

      return TaskScheduleResult(
          task_id=args.task_id,
          event_id=result.scheduled.event_id,
          scheduled_block=result.scheduled.start_dt,
          message=result.message,
      )
  ```

  **Wiring note for `_get_schedule_fn` and `_get_write_tools`:** Add module-level singletons following the `_store` / `init_tools` pattern already in `tools.py`:
  - `_schedule_fn: Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]] | None = None` (ADR-016: async callable_ref type) with `def init_schedule_fn(fn) -> None` (called by `productivity_manifest` alongside `init_tools`). `_get_schedule_fn()` raises `RuntimeError("schedule_fn not initialised")` if unset.
  - `_write_tools: CalendarWriteTools | None = None` with `def init_write_tools(wt: CalendarWriteTools) -> None` (called by `productivity_manifest` at the same time). `_get_write_tools()` raises `RuntimeError("write_tools not initialised")` if unset. This provides `cancel_event` for the auto-cancel re-schedule path. Update `productivity_manifest(store, schedule_fn, write_tools)` signature accordingly.

  **3b. Link-clear in `task_complete`:**

  In the existing `task_complete` callable (which calls `store.complete_task(args.id)` and returns `TaskCompleteResult`), add AFTER the `complete_task` call:

  ```python
  # Clear the Task↔Event link — the block has been consumed (task done).
  # The spawned recurrence next-instance starts with NULL links (needs its own scheduling).
  # B2 fix: use clear_task_schedule_link (NOT update_task with None sentinels — update_task
  # treats None as "no change"; only the dedicated clear method sets the columns to NULL).
  if completed_task.get("calendar_event_id"):
      store.clear_task_schedule_link(args.id)
  ```

  `store.complete_task(id)` returns `dict | None` (the spawned task or None per M8-d-a Task 2). The completed task itself is NOT returned by `complete_task` — add a `store.get_task(args.id)` call BEFORE `store.complete_task(args.id)` to snapshot the pre-complete state (needed to check `calendar_event_id`). Full updated flow:

  ```python
  async def task_complete(args: TaskCompleteArgs) -> TaskCompleteResult:   # ADR-016: callable_ref is async (store.* calls stay sync inside)
      store = _get_store()
      pre_state = store.get_task(args.id)   # snapshot before completion (sync SQLCipher)
      spawned = store.complete_task(args.id)
      # Link-clear: completed task no longer needs its focus-block link
      # B2 fix: clear_task_schedule_link, NOT update_task(..., calendar_event_id=None, ...)
      if pre_state and pre_state.get("calendar_event_id"):
          store.clear_task_schedule_link(args.id)
      return TaskCompleteResult(spawned_task=spawned)
  ```

  Import additions required at top of `tools.py`:
  - `from artemis.modules.calendar.schedule_task import ScheduleTaskArgs, ScheduleTaskResult`
  - `from artemis.modules.calendar.write_tools import CalendarWriteTools, CancelEventArgs`
  - `from collections.abc import Callable, Awaitable`  (ADR-016: async callable_ref types)

  — done when: `uv run mypy --strict src` passes; `task_schedule`/`task_complete` are coroutine functions (`inspect.iscoroutinefunction(...) is True` — ADR-016); `await task_schedule(...)` (async test) with uninitialised `_schedule_fn` raises `RuntimeError`; `await task_schedule(...)` on a task with an existing `calendar_event_id` `await`s `write_tools.cancel_event(CancelEventArgs(event_id=old_id, recurrence_scope="THIS_EVENT"))` BEFORE awaiting `schedule_fn` (assert call order in test); `await task_schedule(...)` on a task with no existing `calendar_event_id` does NOT call `cancel_event`; `await task_complete(...)` on a task with `calendar_event_id` set clears both link fields after completion; `await task_complete(...)` on a task without a link field is a no-op (no error).

- [ ] **Task 4: Add `task.schedule` ToolSpec to the Productivity manifest** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` (modify, additive) —

  **B1 fix — cumulative signature:** after M8-d-a (30 tools, `(store)`) and M8-d-b (this spec, adds 1 tool), the cumulative manifest signature is `productivity_manifest(store, schedule_fn, write_tools)` — these are the keyword-only params added by this spec. Tool count assertion must be **relative**: M8-d-a established 30; this spec adds exactly 1 (`task.schedule`) → assert `len(tools) == 30 + 1 == 31`. M8-d-c1 will add `registry` param; M8-d-c2 will add `capture_service`, `ingest_pipeline`, `memory_queue`.

  In `productivity_manifest(store, schedule_fn, write_tools)` (add `schedule_fn: Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]]` (ADR-016: async callable_ref type) and `write_tools: CalendarWriteTools` as second and third parameters — both added here, both needed because Task 3 wires both `init_schedule_fn` and `init_write_tools`):

  1. Call `init_schedule_fn(schedule_fn)` alongside `init_tools(store)`.
  2. Add one additional `ToolSpec` for `task.schedule`:

  ```python
  ToolSpec(
      name="task.schedule",
      description=(
          "Find an open calendar slot for the given task and create a self-only focus-block event. "
          "Writes task.calendar_event_id and task.scheduled_block on success. "
          "Returns the event_id and block start, or a message if no slot was found. "
          "action_risk: WRITE · always auto (focus blocks are self-only)."
      ),
      args_schema=TaskScheduleArgs,
      return_schema=TaskScheduleResult,
      callable_ref=task_schedule,
      action_risk=ActionRisk.WRITE,
  )
  ```

  This brings the total ToolSpec count from 30 → 31. Update the manifest's `description` or comment to note the count.

  Update `productivity/__init__.py` re-export: `productivity_manifest` signature now accepts `schedule_fn`.

  — done when: `uv run mypy --strict src` passes; `productivity_manifest(store, schedule_fn).name == "productivity"`; `len(productivity_manifest(store, schedule_fn).tools) == 31`; `"task.schedule"` is present in tool names; `"task.complete"` is still present (no regression).

- [ ] **Task 5 (GATED — on-hardware):** Real write-through — on the Mini with vault mounted, `CalendarWriteTools` over real `GoogleCalendarClient`: `task.schedule(task_id=<real task>, window_start=<today>, window_end=<today+3d>)` creates a real Google Calendar event titled `"[Task] <task_title>"`, `task.calendar_event_id` is set, `task.scheduled_block` is set; `task.complete(task_id=<same task>)` clears both fields; the Google event is NOT deleted (the event stands — Artemis does not auto-cancel focus blocks on task completion). → done when: recorded in handoff.

- [ ] **Task 6: Tests (off-hardware, fakes only)** — files: `/Users/artemis-build/artemis/tests/test_time_blocking_seam.py` —

  Typed pytest. Fixtures:
  - `FakeCalendarClient` (from CAL-a) configured with one empty slot.
  - `FakeKeyProvider({"owner-private": os.urandom(32)}, owner_unlocked=True)` + `Settings(data_root=tmp_path)`.
  - `ProductivityStore` via the off-hardware sqlite fallback (same pattern as M8-d-a Task 7).
  - `CalPrefs(focus_block_duration_minutes=60, default_write_calendar="primary", owner_email="me@test.com")`.
  - A `find_time_fn` stub: an **async** `Callable[[FindTimeArgs], Awaitable[FindTimeResult]]` (`async def`, ADR-016) returning a single `FreeSlot(start_dt="2026-06-10T10:00:00Z", end_dt="2026-06-10T11:00:00Z", duration_minutes=60)`.
  - A `FakeCalendarWriteTools` stub with **`async def block_focus_time`** and **`async def cancel_event`** (ADR-016: tool callables are async; does not call Google; records calls; `block_focus_time` returns `WriteResult(event_id="evt-123", summary="[Task] Buy milk", status="executed", tool_name="calendar.block_focus_time")`).

  All tests that drive `schedule_task` / `task_schedule` / `task_complete` are `async def` (ADR-016: these are coroutine functions) and `await` the call (e.g. `pytest.mark.asyncio` / `anyio`, matching the project's existing async-test convention).

  **`schedule_task` — happy path:**
  - `await schedule_task(ScheduleTaskArgs(task_id="t1", task_title="Buy milk"), write_tools=fake_wt, find_time_fn=stub_fn, prefs=prefs)` → `result.scheduled.event_id == "evt-123"`, `result.scheduled.start_dt == "2026-06-10T10:00:00Z"`, `result.scheduled.calendar_id == "primary"` (from `prefs.default_write_calendar`), `result.message` is non-empty.
  - Assert `FakeCalendarWriteTools.block_focus_time` was awaited once with `title="[Task] Buy milk"`.

  **`schedule_task` — no slot:**
  - async `find_time_fn` stub returns `FindTimeResult(slots=[])` → `result.scheduled is None`, `result.message` is non-empty; `block_focus_time` was NOT called.

  **`schedule_task` — estimate_minutes overrides prefs:**
  - `ScheduleTaskArgs(..., estimate_minutes=45)` → `await`ed `find_time_fn` receives `FindTimeArgs(duration_minutes=45, ...)` (assert the arg).

  **`task_schedule` tool — link write round-trip:**
  - Create a task via `ProductivityStore` with `title="Buy milk"`, `estimate_minutes=60`.
  - `init_tools(store)`, `init_schedule_fn(fake_schedule_fn)` where `fake_schedule_fn` is an **async** callable returning a `ScheduleTaskResult` with `scheduled.event_id="evt-456"`, `scheduled.start_dt="2026-06-10T10:00:00Z"`.
  - `await task_schedule(TaskScheduleArgs(task_id=task_id))` → `TaskScheduleResult.event_id == "evt-456"`, `TaskScheduleResult.scheduled_block == "2026-06-10T10:00:00Z"`.
  - `store.get_task(task_id)["calendar_event_id"] == "evt-456"` (link persisted).
  - `store.get_task(task_id)["scheduled_block"] == "2026-06-10T10:00:00Z"` (block persisted).

  **`task_schedule` tool — re-schedule cancels old block:**
  - Create a task; call `store.update_task(task_id, calendar_event_id="evt-old", scheduled_block="2026-06-10T09:00:00Z")` to simulate an already-scheduled state.
  - `await task_schedule(TaskScheduleArgs(task_id=task_id))` → assert `FakeCalendarWriteTools.cancel_event` was awaited with `event_id="evt-old"` BEFORE `fake_schedule_fn` was awaited (track call order); new `event_id="evt-456"` is written to the task row; `"evt-old"` is no longer the stored `calendar_event_id`.
  - Separate case: a task with `calendar_event_id=None` → `FakeCalendarWriteTools.cancel_event` is NOT called.

  **`task_schedule` tool — task not found:**
  - `await task_schedule(TaskScheduleArgs(task_id="nonexistent"))` → `TaskScheduleResult.event_id is None`, `message` mentions "not found"; `store` is not mutated.

  **`task_complete` — link-clear:**
  - Create a task; call `store.update_task(task_id, calendar_event_id="evt-789", scheduled_block="2026-06-10T10:00:00Z")`.
  - `await task_complete(TaskCompleteArgs(id=task_id))` → `store.get_task(task_id)["calendar_event_id"] is None` AND `store.get_task(task_id)["scheduled_block"] is None`.

  **`task_complete` — no link, no error:**
  - Create a task with NULL `calendar_event_id`; `await task_complete(...)` completes without error.

  **Uninitialised `_schedule_fn`:**
  - Without calling `init_schedule_fn`, `await task_schedule(...)` raises `RuntimeError`.

  **Manifest shape:**
  - `productivity_manifest(store, fake_schedule_fn)` has `len(tools) == 31`; `"task.schedule"` in tool names; `"task.complete"` in tool names; all names unique.

  — done when: `uv run pytest -q tests/test_time_blocking_seam.py` passes AND `uv run mypy --strict src tests/test_time_blocking_seam.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/calendar/schedule_task.py` |
| Create | `/Users/artemis-build/artemis/tests/test_time_blocking_seam.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_time_blocking_seam.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_time_blocking_seam.py` | Test gate (fakes only) |
| `uv run pytest -q tests/test_productivity_core.py tests/test_calendar_write.py tests/test_calendar_read.py tests/test_time_blocking_seam.py` | Regression gate (no regressions in prereqs) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/calendar/schedule_task.py`, `src/artemis/modules/calendar/manifest.py`, `src/artemis/modules/productivity/tools.py`, `src/artemis/modules/productivity/manifest.py`, `tests/test_time_blocking_seam.py` |
| `git commit` | `"feat: M8-d-b time-blocking seam — calendar.schedule_task primitive + task.schedule tool + Task↔Event link"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot + data-root resolution (`paths.scope_dir`) |

### Network
| Action | Purpose |
|--------|---------|
| HTTPS to `www.googleapis.com` (GATED, on-Mini only) | Real focus-block event creation (Task 5) |

## Specialist Context

### Security

Three invariants that MUST hold:

1. **`calendar.schedule_task` is unconditionally self-only.** The focus-block event is created via `block_focus_time` which the CAL-b classifier hard-codes as `AUTO` (rule 2: no attendee check, always `AUTO`). The `ScheduleTaskArgs` schema has no `attendee_emails` field — it is structurally impossible to schedule a task block with attendees through this primitive. Any future caller that needs an attendee focus-block must use `calendar.create_event` (→ gated). Document this constraint in `schedule_task.py`.

2. **Task↔Event link integrity.** The `task.calendar_event_id` and `task.scheduled_block` fields are written ONLY after `block_focus_time` returns `status="executed"` (i.e. after a confirmed Google write). If `CalendarWriteError` is raised, `update_task` is NOT called — the task remains un-linked. This ordering is enforced by the function control flow (step 9 in Task 1 runs after step 7's success). No partial link state is possible.

3. **No double-booking / no orphaned blocks.** `calendar.schedule_task` uses `find_time_tool` as its slot source; `find_time_tool` reads from the `EventCacheStore` which includes all existing events (including prior focus-blocks). The `find_time` algorithm excludes busy intervals and applies `buffer_minutes`. A task that is already linked (`calendar_event_id` is set) is re-schedulable — **on re-schedule, the old focus-block is auto-cancelled BEFORE the new block is created.** In `task_schedule` (Task 3 in Phase 2), immediately after `store.get_task(args.task_id)` and BEFORE calling `schedule_fn(...)`, check `task.get("calendar_event_id")` — if set, call `calendar.cancel_event(old_event_id)` (self-only, AUTO per classifier rule 2 for self-only events with no attendees, no gating). This prevents "Task: X" orphan focus-blocks accumulating on the owner's calendar. The cancel call uses `CancelEventArgs(event_id=old_event_id, recurrence_scope="THIS_EVENT")` and is invoked via `write_tools.cancel_event(CancelEventArgs(...))` — it is a self-only event so the classifier resolves AUTO and executes immediately.

Additional:
- `task_title` from `store.get_task(args.task_id)["title"]` is owner-authored data (fully trusted per productivity.md §I posture). No `artemis.untrusted` layer needed.
- `event_id` returned from Google Calendar is a stable external identifier; it is stored as TEXT in the tasks table (no length limit concern at SQLite level).
- `key.as_hex()` is not called in this spec — both stores are accessed via their existing `ProductivityStore`/`CalendarWriteTools` interfaces which already enforce this invariant internally.

[apex-security review: self-only gating is structurally enforced by schema (no attendees field); link-write is post-success only; no new SQLCipher surfaces; task title is trusted. No new injection surface.]

### Performance

`task.schedule` makes one `find_time` cache read + one Google Calendar API write (the `block_focus_time`). The `find_time` call reads from the local `EventCacheStore` (SQLCipher, no network). The Google write is synchronous (one API call). Total latency is dominated by the Google write (typically 200–500ms on-hardware). Acceptable for an on-demand tool (not a hook).

### Accessibility

(none — no frontend in M8-d-b)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/calendar/schedule_task.py` | Docstring: self-only invariant; no-attendees structural constraint; old-event orphan behaviour on re-schedule; slot-empty return semantics |
| Inline | `src/artemis/modules/productivity/tools.py` | Docstring on `task_schedule`: link-write ordering guarantee; docstring on `task_complete`: link-clear behaviour + note that the Google event is NOT deleted |
| Data model | `docs/technical/architecture/data-model.md` | Note that `tasks.calendar_event_id` + `tasks.scheduled_block` (added in M8-d-a) are written by this spec's `task.schedule` tool |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_time_blocking_seam.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_time_blocking_seam.py` → verify (all `schedule_task`/`task_schedule`/`task_complete` calls are `await`ed in async tests — ADR-016): `schedule_task` happy-path sets `event_id` + `start_dt` + awaits `block_focus_time` once; no-slot returns `scheduled=None` + does not call `block_focus_time`; `estimate_minutes` override propagates to `find_time_fn`; `task_schedule` writes `calendar_event_id` + `scheduled_block` to the task row; re-schedule awaits `cancel_event(old_event_id)` BEFORE `schedule_fn` and then overwrites the link; no-prior-link re-schedule does NOT call `cancel_event`; task-not-found returns graceful result; `task_complete` on a linked task clears both link fields; `task_complete` on an unlinked task is a no-op; uninitialised `_schedule_fn` raises `RuntimeError`; manifest has 31 unique tools including `task.schedule`.
- [ ] `uv run pytest -q tests/test_productivity_core.py tests/test_calendar_write.py tests/test_calendar_read.py tests/test_time_blocking_seam.py` → verify: no regressions in any prereq test suite.
- [ ] `uv run python -c "from artemis.modules.calendar.schedule_task import schedule_task, ScheduleTaskArgs; print('ok')"` → verify: prints `ok`.
- [ ] `uv run python -c "from artemis.modules.productivity.tools import task_schedule; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) `task.schedule` creates a real Google Calendar event titled `"[Task] <title>"`; `task.calendar_event_id` and `task.scheduled_block` are written; `task.complete` clears both fields; the Google event remains on the calendar (not auto-deleted) → verify: recorded in handoff.

## Resolved Markers

- **[A — RESOLVED]:** `CalendarWriteTools` is a normal (non-final) class — confirmed by CAL-b Task 3 (`class CalendarWriteTools`, no `@final`). `schedule_task` calls `write_tools.block_focus_time(BlockFocusTimeArgs(...))` via its public method (CAL-b classifier rule 2 forces `block_focus_time` → `AUTO`). No direct dispatch needed.

- **[B — RESOLVED]:** On re-schedule, the old focus-block is auto-cancelled. `task_schedule` calls `write_tools.cancel_event(CancelEventArgs(event_id=old_event_id, recurrence_scope="THIS_EVENT"))` BEFORE creating the new block (self-only → `AUTO`, no gating). No orphaned "Task: X" blocks accumulate on the owner's calendar.

## Progress
_(Coding mode writes here — do not edit manually)_

- [x] Task 1: `calendar.schedule_task` primitive (args/return schemas + async `schedule_task()`)
- [x] Task 2: `schedule_task` ToolSpec on calendar manifest (bare name `schedule_task` → fq `calendar.schedule_task`)
- [x] Task 3: async `task_schedule` + `init_schedule_fn`/`init_write_tools` singletons + B2 link-clear in `task_complete` (pre_state snapshot → `clear_task_schedule_link`)
- [x] Task 4: `schedule` ToolSpec on `tasks_manifest` (bare name → fq `tasks.schedule`)
- [x] Task 6: off-hardware tests (11 passed)
- [ ] Task 5: GATED on-hardware (real Google write-through) — deferred

**Built 2026-06-24 (Codex apex-coder, host-verified). Commit 38b67eb.** mypy --strict clean (100 src files), ruff clean, full suite 388 passed (377 + 11 new). **Reconciliations (logged, all SMALL/in-scope):** (1) stale `/Users/artemis-build/` paths → repo-relative; (2) **bare ToolSpec names** (B9 live convention) used instead of the spec's literal `name="calendar.schedule_task"`/`"task.schedule"` — registry composes the fq id; (3) the spec's signature changes to `make_calendar_manifest`/`tasks_manifest` would have broken ~10 out-of-scope test callers, so the new injection params (`schedule_task_fn`, `schedule_fn`, `write_tools`) were made **optional (default None)** — additive, existing 1-arg/2-arg callers untouched, the new tool appears only when wired; (4) tool-count assertions made **relative** (the spec's `30→31` is pre-Areas-drop/pre-split). No forks.
