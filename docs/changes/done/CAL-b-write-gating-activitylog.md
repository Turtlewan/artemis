---
spec: cal-b-write-gating-activitylog
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-24 (R1 — gated-twin mechanism pinned): the live registry auto-aliased the
     `{tool}_execute` twin to the front-door callable, so GATE-a approve() re-ran CAL-b's attendee
     classifier → re-stage loop (2026-06-10 B1; CAL-b is the first external-effect runtime-gated
     module). RESOLVED per contracts.md Seam 2 D1 mechanism: `ToolSpec` gains optional
     `execute_callable_ref`; registry prefers it for the twin (back-compatible fallback to
     `callable_ref`). CAL-b sets front-door=classify, execute_callable_ref=raw. New Task 0 adds the
     seam to manifest.py + registry.py; Task 5 rewritten to supply execute_callable_ref (no manual
     twin registration, no staging_dispatch_only flag). Analysis: docs/progress/CAL-b-write-gating-activitylog.md. -->
<!-- amended 2026-06-11 per contracts.md (Seams 2, 3, 4) + cal-gate.md BLOCKs B1, B4, B5, B8, B9, B10, F12 -->
<!-- amended 2026-06-11 per contracts.md (Seams 2, 3, 4) + cal-gate.md BLOCKs B1, B4, B5, B8, B9, B10, F12 -->

# Spec: CAL-b — Calendar write/management tools + STRICT auto-vs-gated classifier + activity log + Review-staging integration

**Identity:** Adds the §B write-tool surface to the calendar module (create/update/move/cancel/RSVP/attendees/recurring/quick_add/block_focus_time/set_reminders), the STRICT runtime classifier (any attendee ≠ owner → GATED via pending-action staging; self-only → AUTO write-through + activity log), the owned SQLCipher activity log of unattended auto-actions, and the GATE-a `ActionStagingService` integration that stages gated one-off actions as owner-pending `PendingAction` instances (not recipes — see ADR-012).
→ why: see docs/technical/modules/calendar.md §B · docs/technical/adr/ADR-011-spoke-source-of-truth.md (self-only autonomous; external-effect gated) · docs/technical/adr/ADR-012-gated-action-staging.md (pending-action model, distinct from recipe Review).

<!-- Split rule: ONE logical phase (write surface + gating + log + staging). Exceeds 3 files because
     all five pieces form an inseparable gating unit: write tools call the classifier; the classifier
     calls either write-through (→ log) or the GATE-a staging (→ TAKES_ACTION PendingAction). Splitting
     would leave a write tool that calls nothing, or a classifier with no consumers to test the
     invariant. Justified atomic exception, consistent with M8-a / M0-a / M1-a precedents. Flagged per rules. -->

## Assumptions
- **CAL-a** is complete: `modules/calendar/client.py` (`CalendarClient` port + `GoogleCalendarClient` + `FakeCalendarClient` — all implementing the full read+write surface per Seam 4), `modules/calendar/manifest.py` (module manifest with read tools), `modules/calendar/cache.py` (read-cache + `EventCacheStore` + `EventCacheStore.invalidate(event_id, calendar_id)`), `modules/calendar/preferences.py` (`CalPrefs` with `owner_email: str | None` and `default_write_calendar: str`). **Canonical names (B4 / Seam 4):** class is `CalPrefs` (NOT `CalendarPrefs`), field is `default_write_calendar` (NOT `default_write_calendar_id`), store class is `EventCacheStore` (NOT `CalendarCache`), `invalidate` takes TWO args `(event_id, calendar_id)` (PK is compound). CAL-b adds write method bodies to `client.py` (B5 / Seam 4 — `client.py` IS in CAL-b's Files to Change for write method implementation). → impact: Stop.
- **M8-a** is complete: `GoogleCredentialsFactory.authorized_credentials()`, `register_google_scopes`. CAL-b calls `register_google_scopes("calendar_write", {"https://www.googleapis.com/auth/calendar.events"})` at module import. → impact: Stop.
- **M1-a** is complete: `ActionRisk` (`NO_DATA`, `READ`, `WRITE`, `HIGH_STAKES`), `ToolSpec`, `ModuleManifest`, `DataScope.OWNER_PRIVATE`. → impact: Stop.
- **GATE-a** is complete: `PendingAction` model, `ActionStatus` enum, `PendingActionStore`, `ActionStagingService` with `stage(module, tool, args, summary, *, ttl) -> PendingAction` and `approve(id) -> PendingAction`. CAL-b's gated path calls `staging.stage(module="calendar", tool=f"calendar.{tool_name}", args=<bound args dict>, summary=<plain-language description>)` and returns WITHOUT executing the Google write. The owner later approves via the Review screen → GATE-b → `ActionStagingService.approve` re-dispatches the calendar write tool through `ToolRegistry`. → impact: Stop (GATE-a must be complete; these exact symbols are required).
- **CLIENT-b** is complete: the pending-actions surface (`GET /app/actions/pending`) surfaces `PendingAction` rows for the owner's approval (ADR-012 §4 — distinct from the recipe Review endpoint). The CAL-b gated path does NOT call HTTP — it calls `ActionStagingService.stage(...)` which writes to `PendingActionStore`; the Review screen reads from the same store. → impact: Caution (the chain is store-mediated, not direct RPC; verify CLIENT-b has been extended with `/app/actions/*` per ADR-012 §4 before executing Task 7).
- Owner email is resolved once from `CalendarPrefs.owner_email` (populated by CAL-a from the authenticated Google account primary email); this value is the identifier for "self" in all attendee checks. → impact: Stop (if `owner_email` is absent/empty, the classifier MUST treat the event as having attendees → GATED, fail-safe).
- The runtime classifier gate (`event.attendees minus owner`) is the REAL security boundary; `ToolSpec.action_risk` is a baseline hint only — it does NOT override the runtime check. → impact: Stop.
- `respond_to_invite` is ALWAYS gated (acts toward others) regardless of attendee list. `block_focus_time` and `set_reminders` are ALWAYS auto (self-only by design). For all other tools, the classifier checks `event.attendees`. → impact: Stop.
- Recurrence edits use Google's three-scope semantics: `THIS_EVENT`, `THIS_AND_FOLLOWING`, `ALL_EVENTS`. A recurring event with attendees → gated like any attendee event. → impact: Caution.
- On Google write-through success, the read-cache is invalidated via `cache.invalidate(event_id)` (CAL-a's `cache.py`). On failure, a typed `CalendarWriteError` is raised — never silently dropped. → impact: Stop.
- SQLCipher `activity_log.db` follows the exact `SqlCipherTokenStore` pattern from M8-a: keyed `_connect`, `ScopeLockedError` propagates, `key.as_hex()` local-only, path under `paths.scope_dir(settings, OWNER_PRIVATE) / "calendar" / "activity_log.db"` (vault-path reconciliation deferred to on-hardware integration, same deferral as M8-a Task 7 / M3-a). → impact: Stop.
- Off-hardware: all tests run against `FakeCalendarClient`, `FakeKeyProvider`, and a `FakeActionStagingService` (spy; records `stage(...)` calls, returns a minimal `PendingAction`) over a `tmp_path`. On-hardware-gated: real Google write-through, real SQLCipher activity log, real staging round-trip to the Review screen. → impact: Stop (keeps CI off-hardware-buildable).
- M1-d module layout: `src/artemis/modules/calendar/` is the confirmed package path (matches GATE-a's `src/artemis/staging/` convention; both are under `src/artemis/`; no conflict). M1-d marker resolved — no further verification needed.

Simplicity check: considered routing GATED through an HTTP call to the Review endpoint directly — rejected; the store-mediated path (call `ActionStagingService.stage(...)`, Review screen reads `PendingActionStore`) is the ADR-012 contract and avoids coupling the calendar module to the HTTP layer. Considered a single `write_tools.py` file containing the classifier + log — rejected; the brief explicitly separates them for independent testability of the safety-critical classifier. This is the minimum three-file split the brief specifies.

## Prerequisites
- Specs that must be complete first: **CAL-a** (CalendarClient, cache, prefs, manifest), **M8-a** (GoogleCredentialsFactory, register_google_scopes), **M1-a** (ActionRisk, ToolSpec, ModuleManifest, ToolRegistry), **GATE-a** (PendingAction, ActionStatus, PendingActionStore, ActionStagingService — the staging seam CAL-b's gated path calls), **M2-b/M2-c** (KeyProvider, ScopeLockedError, sqlcipher_open, OWNER_PRIVATE), **M0-a** (Settings, paths.scope_dir).
- Environment setup required: none beyond CAL-a. Off-hardware fully testable with fakes. Real Google writes + real SQLCipher + real Review staging round-trip are GATED on-hardware (Task 7).

## Files to Change

Paths are repo-relative (build runs with the repo root as CWD). The CalendarClient Protocol +
`GoogleCalendarClient`/`FakeCalendarClient` already declare the write methods (CAL-a, currently
`raise NotImplementedError`); CAL-b fills the bodies.

| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/manifest.py | modify | **Task 0 (R1 seam):** add optional `execute_callable_ref: Callable[..., Awaitable[BaseModel]] \| None = None` to `ToolSpec` (contracts.md Seam 2 D1 mechanism). Additive, defaults None — back-compatible. |
| src/artemis/registry/registry.py | modify | **Task 0 (R1 seam):** in `register()`, map `{fq}_execute` → `tool.execute_callable_ref or tool.callable_ref`. Additive — existing modules (no `execute_callable_ref`) keep current behaviour. |
| src/artemis/modules/calendar/client.py | modify | add write method bodies to `GoogleCalendarClient` + `FakeCalendarClient` (B5 / Seam 4 — the canonical write methods already declared in the CalendarClient Protocol by CAL-a, kw-only signatures). `FakeCalendarClient` records calls + supports raise-on-call for the failure test. |
| src/artemis/modules/calendar/write_tools.py | create | §B args/return schemas, `CalendarWriteError`, `CalendarWriteTools` (front-door classify methods + `*_raw` execute methods), action_risk baselines |
| src/artemis/modules/calendar/gating.py | create | runtime classifier `classify()`, stage-vs-execute dispatch `dispatch()`, `GateDecision` enum |
| src/artemis/modules/calendar/activity_log.py | create | SQLCipher append-only activity log of auto-actions (mirror `SqlCipherTokenStore` at `src/artemis/integrations/google/tokens.py`) |
| src/artemis/modules/calendar/manifest.py | modify | add write `ToolSpec`s (front-door `callable_ref` + raw `execute_callable_ref`) to the existing manifest factory; wire a `CalendarWriteTools` instance |
| tests/test_calendar_write.py | create | classifier truth table, AUTO executes+logs, GATED stages-only, approve→raw-twin executes (no re-stage), recurrence, write-failure, locked-store |
| tests/test_registry.py | modify | **Task 0:** assert `{fq}_execute` resolves to `execute_callable_ref` when set, falls back to `callable_ref` when not (add to the existing registry test file; create if absent) |

## Tasks

- [ ] Task 0: Add the `execute_callable_ref` seam (R1) — files: `src/artemis/manifest.py`, `src/artemis/registry/registry.py`, `tests/test_manifest_registry.py` —

  **manifest.py:** add to `ToolSpec` an optional field
  `execute_callable_ref: Callable[..., Awaitable[BaseModel]] | None = None` (after `callable_ref`).
  Additive, default `None`. Document it: "raw classifier-free twin for runtime-gated tools; the
  registry maps `{fq}_execute` to it; never a `ToolSpec.name`, so it stays out of `retrieve_tools()`."

  **registry.py:** in `register()`, the existing twin line becomes:
  ```python
  if tool.action_risk in (ActionRisk.WRITE, ActionRisk.HIGH_STAKES):
      exec_id = f"{fq_id}_execute"
      self._execute_callables[exec_id] = tool.execute_callable_ref or tool.callable_ref
  ```
  No other change — `get_tool` already wraps `_execute_callables[fq]` in a synthetic ToolSpec.

  **tests/test_manifest_registry.py:** add two cases — (a) a `WRITE` tool with a distinct
  `execute_callable_ref` → `get_tool("mod.tool_execute").callable_ref is <the raw fn>` (not the
  front door); (b) a `WRITE` tool with no `execute_callable_ref` → `{fq}_execute` falls back to
  `callable_ref` (back-compat).

  Done when: `uv run mypy --strict src` passes; `uv run pytest -q tests/test_manifest_registry.py`
  passes (incl. the two new cases); existing registry tests unchanged-green.

- [ ] Task 1: Define write-tool args/return schemas and `GatingResult` types — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/write_tools.py` —

  Pydantic v2 `BaseModel` schemas (all `model_config = ConfigDict(frozen=True)`):

  **Shared types:**
  - `RecurrenceScope = Literal["THIS_EVENT", "THIS_AND_FOLLOWING", "ALL_EVENTS"]`
  - `SendUpdates = Literal["all", "externalOnly", "none"]` (used on gated writes that do execute; default `"all"` for attendee events — the classifier decides, not the tool arg)
  - `ReminderMethod = Literal["email", "popup"]`
  - `Reminder(method: ReminderMethod, minutes_before: int)`

  **Args schemas** (one per tool):
  - `CreateEventArgs(summary: str, start_datetime: str, end_datetime: str, description: str | None = None, location: str | None = None, attendee_emails: list[str] = [], calendar_id: str | None = None, recurrence: list[str] = [], reminders: list[Reminder] = [])`
  - `UpdateEventArgs(event_id: str, summary: str | None = None, start_datetime: str | None = None, end_datetime: str | None = None, description: str | None = None, location: str | None = None, recurrence_scope: RecurrenceScope = "THIS_EVENT")`
  - `MoveEventArgs(event_id: str, new_start_datetime: str, new_end_datetime: str, recurrence_scope: RecurrenceScope = "THIS_EVENT")`
  - `CancelEventArgs(event_id: str, recurrence_scope: RecurrenceScope = "THIS_EVENT")`
  - `RespondToInviteArgs(event_id: str, response: Literal["accepted", "declined", "tentative"])`
  - `AddAttendeesArgs(event_id: str, attendee_emails: list[str])`
  - `RemoveAttendeesArgs(event_id: str, attendee_emails: list[str])`
  - `CreateRecurringEventArgs(summary: str, start_datetime: str, end_datetime: str, rrule: str, attendee_emails: list[str] = [], description: str | None = None, calendar_id: str | None = None)`
  - `QuickAddArgs(text: str, calendar_id: str | None = None)`
  - `BlockFocusTimeArgs(start_datetime: str, end_datetime: str, title: str = "Focus time", calendar_id: str | None = None)`
  - `SetRemindersArgs(event_id: str, reminders: list[Reminder])`

  **Return schemas** (shared):
  - `WriteResult(event_id: str, summary: str, status: Literal["executed", "staged_for_review"])`
  - `StagedResult(pending_action_id: str, summary: str, status: Literal["staged_for_review"] = "staged_for_review")`

  **Write error:**
  - `class CalendarWriteError(Exception)`: carries `message: str`, `event_id: str | None = None`, `http_status: int | None = None`. Never silently swallowed; always raised on Google API failure.

  Done when: `uv run mypy --strict src` passes; all schema classes construct with valid args.

- [ ] Task 2: Implement the STRICT runtime classifier — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/gating.py` —

  ```python
  from enum import Enum

  class GateDecision(str, Enum):
      AUTO = "auto"
      GATED = "gated"

  def classify(
      tool_name: str,
      attendees: list[str],   # raw attendee emails from the Google event (or args)
      owner_email: str,
  ) -> GateDecision:
  ```

  Rules (encode exactly, in order — this is the security boundary):
  1. `tool_name in {"respond_to_invite"}` → `GATED` (always; acts toward others)
  2. `tool_name in {"block_focus_time", "set_reminders", "quick_add"}` → `AUTO` (always; self-only by design — `quick_add` added per B10 / Seam 4: Google quickAdd cannot create attendees from text)
  3. `non_owner = [e for e in attendees if e.lower().strip() != owner_email.lower().strip()]` → if `len(non_owner) > 0` → `GATED`
  4. `else` → `AUTO`

  Failsafe: if `owner_email` is empty string → treat as having attendees → `GATED` (fail-safe; never auto-write when identity is unknown).

  ```python
  async def dispatch(
      tool_name: str,
      event_id: str | None,
      attendees: list[str],
      owner_email: str,
      *,
      execute_fn: Callable[[], Awaitable[WriteResult]],
      stage_fn: Callable[[], Awaitable[StagedResult]],
      log_fn: Callable[[WriteResult], None],
  ) -> WriteResult | StagedResult:
  ```

  **ADR-016 (uniform async tool-dispatch):** `dispatch` is `async def` because it is called from inside an `async def` `CalendarWriteTools` tool method (a `callable_ref`), and `execute_fn`/`stage_fn` are the per-tool async closures it awaits. `classify()` stays a pure sync function (it is NOT a tool callable). `log_fn` stays **sync** — it is `activity_log.record`, a local SQLCipher write (ADR-016 keeps SQLCipher inside async bodies sync).

  Logic: `decision = classify(tool_name, attendees, owner_email)`. If `AUTO`: `result = await execute_fn()`; `log_fn(result)`; return result. If `GATED`: return `await stage_fn()` (do NOT call `execute_fn`).

  Done when: `uv run mypy --strict src` passes; truth table verified in tests (Task 6).

- [ ] Task 3: Implement the §B write tools — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/write_tools.py` (same file as Task 1, additive) —

  `class CalendarWriteTools` constructed with `(client: CalendarClient, cache: EventCacheStore, prefs: CalPrefs, staging: ActionStagingService, activity_log: "ActivityLog")`. **Canonical names (B4 / Seam 4):** `cache` is `EventCacheStore` (NOT `CalendarCache`), `prefs` is `CalPrefs` (NOT `CalendarPrefs`), `prefs.default_write_calendar` (NOT `default_write_calendar_id`). One method per §B tool.

  **ADR-016 (uniform async tool-dispatch):** every front-door tool method is `async def` (each is a `ToolSpec.callable_ref`); the method `await`s `dispatch(...)`. The `execute_fn`/`stage_fn` closures are `async def` (awaited by `dispatch`). The underlying `CalendarClient` write methods are sync per Seam 4, so `execute_fn`'s body calls them without `await`; `cache.invalidate` and `staging.stage` are also sync (local SQLCipher) — the `async def` on the closures is for the uniform-await dispatch contract.

  Each method:
  1. Resolves attendees from args or (for update/move/cancel) fetches the existing event via `client.get_event(event_id)` to read its `attendees` field (sync Seam 4 client — no `await`).
  2. `return await dispatch(tool_name, event_id, attendees, prefs.owner_email, execute_fn=..., stage_fn=..., log_fn=activity_log.record)`.
  3. The `async def execute_fn` calls the appropriate `CalendarClient` method (see below; sync Seam 4 call, no `await`), then calls `cache.invalidate(event_id, calendar_id)` on success (B4: two-arg signature). On `CalendarClient` error, raises `CalendarWriteError`.
  4. The `async def stage_fn` calls `staging.stage(module="calendar", tool=f"calendar.{tool_name}", args=args.model_dump(), summary=<plain-language description of the external effect>)` (`stage` is sync per Seam 3 — no `await`). The summary must be deterministic and human-readable (e.g. `"Cancel event 'Team sync' — has attendees Alice, Bob; pending owner approval"`). Returns `StagedResult(pending_action_id=action.id, summary=action.summary)` where `action` is the returned `PendingAction`. Does NOT execute the Google write — the action is now PENDING; the owner approves it via the Review screen → GATE-b → `ActionStagingService.approve` dispatches the `_execute` twin via ToolRegistry (NOT the front-door tool — see B1 / Seam 3 D1).

  **Live CalendarClient signatures (CAL-a, Seam 4 — read `client.py`; these are authoritative over the sketch below):** all write methods are **keyword-only** and currently `raise NotImplementedError` (CAL-b fills them). Names: `create_event(*, summary, start, end, description=None, location=None, attendees: tuple[str,...]=(), calendar_id, recurrence: tuple[str,...]=(), reminders: dict[str,object]|None=None, send_updates="all")` (note `start`/`end`, NOT `start_datetime`; `attendees`/`recurrence` are **tuples**; `reminders` is a **dict**), `update_event(event_id, changes: dict, *, recurrence_scope, send_updates="all")`, `move_event(event_id, *, new_start, new_end, recurrence_scope, send_updates="all")`, `cancel_event(event_id, *, recurrence_scope, send_updates="all") -> None`, `respond_to_invite(event_id, response)`, `add_attendees(event_id, attendee_emails: list[str], *, send_updates="all")`, `remove_attendees(...)`, `quick_add(text, calendar_id)`, `set_reminders(event_id, reminders: list[dict])`, `get_event(calendar_id, event_id)` (calendar_id FIRST). The `execute_fn`/`*_raw` body maps the Pydantic `Args` fields → these kwargs (e.g. `args.start_datetime`→`start=`, `tuple(args.attendee_emails)`→`attendees=`, `[r.model_dump() for r in args.reminders]`→`reminders=`). `calendar_id` falls back to `prefs.default_write_calendar` when `args.calendar_id is None`.

  **CalendarClient method mapping** (one call per tool; abstract — adapt to the live kw-only signatures above):
  - `create_event(args)` → `client.create_event(summary, start, end, description, location, attendees, calendar_id, recurrence, reminders, send_updates="all")`
  - `update_event(args)` → `client.update_event(event_id, changes_dict, recurrence_scope, send_updates="all")`
  - `move_event(args)` → `client.move_event(event_id, new_start, new_end, recurrence_scope, send_updates="all")`
  - `cancel_event(args)` → `client.cancel_event(event_id, recurrence_scope, send_updates="all")`
  - `respond_to_invite(args)` → `client.respond_to_invite(event_id, response)` (always gated; this line is the gated-path execute_fn — only runs after owner approval)
  - `add_attendees(args)` → `client.add_attendees(event_id, attendee_emails, send_updates="all")`
  - `remove_attendees(args)` → `client.remove_attendees(event_id, attendee_emails, send_updates="all")`
  - `create_recurring_event(args)` → `client.create_event(...)` with `recurrence=[args.rrule]`
  - `quick_add(args)` → always-AUTO (B10 / Seam 4): Google `quickAdd` cannot create attendees from text, so this tool is always self-only; dispatch directly via `client.quick_add(text, calendar_id)` with no attendee-resolve step. The classifier is NOT called for `quick_add` — treat it like `block_focus_time` (same always-AUTO encoding in `classify()` rule 2).
  - `block_focus_time(args)` → `client.create_event(title, start, end, calendar_id=args.calendar_id)` (no attendees; always auto)
  - `set_reminders(args)` → `client.set_reminders(event_id, reminders)` (always auto)

  `sendUpdates` policy: gated-path execute_fn (post-owner-approval) uses `"all"` for create/update/move/cancel/attendee changes. Auto-path (self-only) uses `"none"` (no other attendees to notify by definition).

  Done when: `uv run mypy --strict src` passes; AUTO tools call execute+log and do NOT call stage_fn; GATED tools call stage_fn and do NOT call execute_fn (Task 6 asserts the `FakeCalendarClient` write methods).

- [ ] Task 4: Implement the SQLCipher activity log — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/activity_log.py` —

  Mirror the `SqlCipherTokenStore` pattern from M8-a exactly (keyed `_connect`, `ScopeLockedError` propagation, `key.as_hex()` local-only).

  ```python
  @dataclass(frozen=True)
  class ActivityLogEntry:
      id: int
      ts_ms: int               # epoch ms
      tool_name: str
      event_id: str | None
      event_summary: str | None
      result_status: str       # "executed"
      error: str | None        # non-None if CalendarWriteError was caught post-log (should not happen; here for schema completeness)

  class ActivityLog:
      def __init__(self, settings: Settings, key_provider: KeyProvider) -> None: ...

      def _db_path(self) -> Path:
          # paths.scope_dir(settings, OWNER_PRIVATE) / "calendar" / "activity_log.db"
          # vault-path reconciliation deferred to on-hardware (same deferral as M8-a Assumptions)

      def _connect(self) -> Connection:
          # key = key_provider.dek_for_scope(OWNER_PRIVATE)   # raises ScopeLockedError if locked
          # key.as_hex() assigned ONLY as a local variable (never instance attr — same rule as M8-a)
          # CREATE TABLE IF NOT EXISTS activity_log (
          #   id INTEGER PRIMARY KEY AUTOINCREMENT,
          #   ts_ms INTEGER NOT NULL,
          #   tool_name TEXT NOT NULL,
          #   event_id TEXT,
          #   event_summary TEXT,
          #   result_status TEXT NOT NULL,
          #   error TEXT
          # )

      def record(self, result: WriteResult) -> None:
          # INSERT INTO activity_log (ts_ms, tool_name, event_id, event_summary, result_status)
          # VALUES (now_ms(), result.tool_name, result.event_id, result.summary, result.status)
          # ScopeLockedError propagates (caller: dispatch's log_fn; a locked store means
          # Artemis cannot log the auto-action → treat as a write failure upstream)

      def recent(self, limit: int = 50) -> list[ActivityLogEntry]:
          # SELECT ... ORDER BY ts_ms DESC LIMIT limit
          # ScopeLockedError propagates
  ```

  **Important:** `WriteResult` does not currently carry `tool_name` — add `tool_name: str` to `WriteResult` in `write_tools.py` (Task 1 additive fix). The `execute_fn` in `dispatch` must supply this.

  Done when: `uv run mypy --strict src` passes; `ActivityLog` with `FakeKeyProvider(owner_unlocked=False)` raises `ScopeLockedError` on `record` and `recent`; a round-trip `record` + `recent` returns the entry (Task 6).

- [ ] Task 5: Add write ToolSpecs to the manifest + register `_execute` twins — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` (modify, additive only), `/Users/artemis-build/artemis/src/artemis/modules/calendar/client.py` (modify, additive — write method bodies + execute-twin helpers) —

  **B9 / F12 / Seam 2 — ToolSpec.name is BARE:** `ToolSpec.name` must be the bare tool name (e.g. `"create_event"`), NOT the qualified form (NOT `"calendar.create_event"`). The registry composes the fq id as `f"{manifest.name}.{tool.name}"` = `"calendar.create_event"`. `stage(tool=...)` and `get_tool(...)` use the fq id. A literal executor that writes `ToolSpec(name="calendar.create_event")` produces registry id `"calendar.calendar.create_event"` (double-prefix) and GATE-a approve raises `KeyError`. **`ToolSpec.name` is bare; `module.tool` is the registry id used by `stage()`/`get_tool()`.**

  **Factory signature:** extend the live `make_calendar_manifest(tools: CalendarTools) -> ModuleManifest` to `make_calendar_manifest(tools: CalendarTools, write_tools: CalendarWriteTools) -> ModuleManifest` (read ToolSpecs from `tools` as today + the 11 write ToolSpecs from `write_tools`). Blast radius is just the `__init__.py` re-export docstring (no composition root calls it yet) + the CAL-b test. Keep read ToolSpecs unchanged.

  For each §B write tool add a `ToolSpec` to the manifest's `tools` list with bare names. Exact `action_risk` baselines (the runtime classifier is the real gate; these are hint-only):

  | tool_name (BARE) | action_risk baseline |
  |---|---|
  | `block_focus_time` | `ActionRisk.WRITE` |
  | `create_event` | `ActionRisk.HIGH_STAKES` |
  | `update_event` | `ActionRisk.HIGH_STAKES` |
  | `move_event` | `ActionRisk.HIGH_STAKES` |
  | `cancel_event` | `ActionRisk.HIGH_STAKES` |
  | `respond_to_invite` | `ActionRisk.HIGH_STAKES` |
  | `add_attendees` | `ActionRisk.HIGH_STAKES` |
  | `remove_attendees` | `ActionRisk.HIGH_STAKES` |
  | `create_recurring_event` | `ActionRisk.HIGH_STAKES` |
  | `quick_add` | `ActionRisk.WRITE` |
  | `set_reminders` | `ActionRisk.WRITE` |

  Each `ToolSpec` uses the corresponding `Args` and `Return` schema from `write_tools.py`. The `callable_ref` points to the matching `CalendarWriteTools` method (bound method reference; the manifest is constructed with a `CalendarWriteTools` instance by the module factory — `make_calendar_manifest(tools)` factory pattern from CAL-a).

  **B1 / Seam 2 D1 (R1 mechanism) — supply `execute_callable_ref` for each gated tool:** For every tool that can be GATED (`create_event`, `update_event`, `move_event`, `cancel_event`, `respond_to_invite`, `add_attendees`, `remove_attendees`, `create_recurring_event`), the `ToolSpec`'s `execute_callable_ref` points at the matching **raw** `CalendarWriteTools` method (e.g. `tools.create_event_raw`) while `callable_ref` points at the front-door classify method (e.g. `tools.create_event`). The registry (Task 0) maps `{fq}_execute` → `execute_callable_ref`, so GATE-a's async `approve` dispatches the raw write via `await get_tool(f"{action.tool}_execute").callable_ref(validated_args)` with **no classification**. The raw method:
  - is **`async def`** (ADR-016), performs the raw Google write directly (sync Seam-4 `CalendarClient` call, then `cache.invalidate(event_id, calendar_id)` on success); **no `dispatch()`, no `classify()`, no `staging.stage`**. It does **NOT** write the activity log — that log is for unattended AUTO actions only (security invariant); an approved write is recorded by its `PendingAction` (status `APPROVED` + `result`). Activity-log writes happen only on the AUTO path (dispatch's `log_fn`). The `*_raw` method is therefore the shared raw-write+invalidate body; the front-door AUTO path reaches it through `dispatch(execute_fn=self.<tool>_raw, log_fn=activity_log.record)`.
  - takes the SAME args model as the front-door tool (`CreateEventArgs`, etc.) so GATE-a's `args_schema.model_validate(action.args)` works (registry's synthetic twin ToolSpec reuses the base `args_schema`).
  - is **never** a `ToolSpec.name` in `manifest.tools` — only reachable through `{fq}_execute`, so it stays out of `retrieve_tools()` / the brain surface (security invariant: the model never calls the ungated write directly).

  Always-AUTO tools (`block_focus_time`, `set_reminders`, `quick_add`) need **no** `execute_callable_ref` — they never stage, so their front-door is already the executed path. (The registry still creates a fallback `{fq}_execute` = front-door for the `WRITE`-risk ones; harmless, never dispatched since they never stage.)

  Register scopes at module import: `register_google_scopes("calendar_write", {"https://www.googleapis.com/auth/calendar.events"})`.

  **B8 — no import-time `CALENDAR_MANIFEST` constant:** CAL-a deliberately ships only `make_calendar_manifest(tools: CalendarTools) -> ModuleManifest`. Do NOT add a module-level `CALENDAR_MANIFEST` singleton. The acceptance check below must build the manifest via the factory with fakes (not import a constant).

  Done when: `uv run mypy --strict src` passes; all ToolSpec names in the manifest are bare (no `calendar.` prefix); `_execute` twins are registered and accessible via `tool_registry.get_tool("calendar.create_event_execute")` but NOT returned by `retrieve_tools()`.

- [ ] Task 6: Write tests (off-hardware, fakes only) — files: `/Users/artemis-build/artemis/tests/test_calendar_write.py` —

  Typed pytest. **ADR-016:** tests that invoke a `CalendarWriteTools` method or an `_execute` twin `callable_ref` must `await` it (they are `async def`); those tests are `async def` under `pytest.mark.asyncio`. `classify()` is called directly and stays a sync call (not a callable). `FakeActionStagingService.stage` stays a **sync** spy method (Seam 3 `stage` is sync). Fixtures: `FakeCalendarClient` (from CAL-a), `FakeKeyProvider`, `FakeActionStagingService` (in-test spy; records all `stage(module, tool, args, summary, ...)` calls and returns a minimal `PendingAction(id="fake-id-...", module=module, tool=tool, args=args, summary=summary, action_class="takes-action", status=ActionStatus.PENDING, created_at=..., expires_at=...)`; also exposes `.staged: list[PendingAction]` for assertions), `ActivityLog` over `tmp_path` with unlocked `FakeKeyProvider`, `CalendarWriteTools` instance wiring all fakes.

  **Classifier truth table** (call `classify()` directly):
  - `("block_focus_time", [], "me@x.com")` → `AUTO`
  - `("set_reminders", ["me@x.com", "other@x.com"], "me@x.com")` → `AUTO` (always auto)
  - `("respond_to_invite", [], "me@x.com")` → `GATED` (always gated)
  - `("create_event", [], "me@x.com")` → `AUTO` (no attendees)
  - `("create_event", ["me@x.com"], "me@x.com")` → `AUTO` (only owner)
  - `("create_event", ["me@x.com", "other@x.com"], "me@x.com")` → `GATED`
  - `("cancel_event", ["other@x.com"], "me@x.com")` → `GATED`
  - `("create_event", [], "")` → `GATED` (empty owner_email failsafe)
  - `("update_event", ["other@x.com"], "me@x.com")` → `GATED`

  **AUTO path — executes and logs, does NOT stage:**
  - `block_focus_time(BlockFocusTimeArgs(...))` with `FakeCalendarClient` → `FakeCalendarClient.create_event` was called once; `activity_log.recent()` has one entry with `tool_name="calendar.block_focus_time"`, `result_status="executed"`; `FakeActionStagingService.staged` is empty (no `stage(...)` call).

  **GATED path — stages a PendingAction and does NOT execute:**
  - `create_event(CreateEventArgs(..., attendee_emails=["other@x.com"]))` → `FakeCalendarClient.create_event` was NOT called; `FakeActionStagingService.staged` has exactly one entry; assert `staged[0].module == "calendar"`, `staged[0].tool == "calendar.create_event"`, `staged[0].args` contains the bound create-event args dict, `staged[0].summary` is a non-empty string; `activity_log.recent()` is empty (gated = no log entry, never executed).

  **Approve round-trip executes the RAW twin, no re-stage (B1 regression — the load-bearing test):**
  Using the REAL `ActionStagingService` + REAL `ToolRegistry` (register the calendar manifest built
  via `make_calendar_manifest`), with a `FakeCalendarClient` and unlocked `FakeKeyProvider`:
  - `create_event(CreateEventArgs(..., attendee_emails=["other@x.com"]))` → one `PENDING` action in
    the store, `FakeCalendarClient.create_event` NOT called.
  - `await staging.approve(action.id)` → `FakeCalendarClient.create_event` **is** called exactly once;
    the action transitions to `APPROVED`; **no second `PENDING` action is created** (store has zero
    pending after approve). This proves `{tool}_execute` dispatched the raw twin, not the classifier.

  **RSVP always gated:**
  - `respond_to_invite(RespondToInviteArgs(event_id="e1", response="accepted"))` → `FakeCalendarClient.respond_to_invite` NOT called; `FakeActionStagingService.staged` has exactly one entry with `tool == "calendar.respond_to_invite"` and `summary` non-empty.

  **Recurrence scopes (AUTO path):**
  - `cancel_event(CancelEventArgs(event_id="e1", recurrence_scope="THIS_AND_FOLLOWING"))` on a self-only event → `FakeCalendarClient.cancel_event` called with `recurrence_scope="THIS_AND_FOLLOWING"`.

  **Write failure surfaces:**
  - When `FakeCalendarClient.create_event` raises, `block_focus_time` raises `CalendarWriteError` (not silently dropped). Activity log entry is NOT written (write failed before log).

  **Locked store — ScopeLockedError:**
  - `ActivityLog(settings, FakeKeyProvider(owner_unlocked=False)).record(...)` raises `ScopeLockedError`.

  **Cache invalidation:**
  - After an AUTO `update_event`, `FakeEventCacheStore.invalidate` was called with `(event_id, calendar_id)` — two-arg signature (B4 / Seam 4).

  **Manifest factory (tool count + bare names):**
  - Build the manifest via `make_calendar_manifest(tools)` with the `CalendarWriteTools` instance wired to the fakes (the same `tools` fixture used above); assert `len(manifest.tools) == <CAL-a read tools> + 11 write tools` and `all("." not in t.name for t in manifest.tools)` (B9 — bare names, no double-prefix). (Replaces the former non-runnable `tools=None` `python -c` AC.)

  Done when: `uv run pytest -q tests/test_calendar_write.py` passes AND `uv run mypy --strict src tests/test_calendar_write.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] Task 7 (GATED — on-hardware / owner-present): Real write-through + real activity log + real Review staging — on the Mini, vault unlocked, real `GoogleCredentialsFactory`:
  - (a) `block_focus_time` creates a real event on the default write calendar; `activity_log.recent()` shows the entry; the event appears in the read-cache after `cache.invalidate`.
  - (b) `create_event` with an attendee email → the gated path fires; `PendingActionStore` has one `PENDING` action with `module="calendar"`, `tool="calendar.create_event"`, non-empty `summary`, and bound args; `GET /app/actions/pending` returns it on the CLIENT-b pending-actions surface (ADR-012 §4).
  - (c) Approve the staged action via `ActionStagingService.approve(action.id)` → the write executes (Google event is created with the attendee); the `PendingAction.status` transitions to `APPROVED`; `result` is non-None.
  - (d) Confirm no event content or attendee email appears in any log file.
  - (e) `update_event` on a recurring self-event with `recurrence_scope="ALL_EVENTS"` → all instances updated on Google.
  Done when: (a)–(e) verified on the Mini and recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/modules/calendar/write_tools.py, /Users/artemis-build/artemis/src/artemis/modules/calendar/gating.py, /Users/artemis-build/artemis/src/artemis/modules/calendar/activity_log.py, /Users/artemis-build/artemis/tests/test_calendar_write.py |
| Modify | /Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_calendar_write.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_calendar_write.py` | Test gate (classifier truth table + AUTO/GATED invariant) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/modules/calendar/write_tools.py, src/artemis/modules/calendar/gating.py, src/artemis/modules/calendar/activity_log.py, src/artemis/modules/calendar/manifest.py, tests/test_calendar_write.py |
| `git commit` | "feat: CAL-b calendar write tools + strict auto-vs-gated classifier + activity log + Review staging" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` / `ARTEMIS_DATA_ROOT` / `ARTEMIS_SLOT` | Settings + scope_dir path resolution (M0-a) |

### Network
| Action | Purpose |
|--------|---------|
| HTTPS to `www.googleapis.com` (GATED, on-Mini only) | Real calendar write-through (Task 7) |

## Specialist Context

### Security

The classifier in `gating.py` is the load-bearing security boundary. The spec enforces three invariants that MUST hold across every code path:

1. **AUTO never fires for an attendee event.** The `classify()` function is the single source of truth; `dispatch()` calls it before deciding. No caller can pass an `override` flag. The `FakeCalendarClient` write-method call assertion in Task 6 is the safety-critical test — a failing assertion here is a security regression.

2. **GATED path NEVER calls the write API.** `dispatch()` calls either `execute_fn` OR `stage_fn` — never both. The test asserts `FakeCalendarClient.create_event` call count == 0 on the GATED path; `FakeActionStagingService.staged` count == 1 and carries the correct tool + bound args.

3. **`respond_to_invite` is unconditionally gated.** Encoded as a first-match rule in `classify()` before any attendee check so it cannot be bypassed by an empty attendee list.

Additional invariants:
- Failsafe for empty `owner_email` → GATED (defend against an uninitialised prefs store).
- Activity log entries are written ONLY for AUTO (executed) actions, never for GATED (staged) ones. The log is not a staging queue.
- `key.as_hex()` is a local variable in `_connect()` — never an instance attribute. Consistent with the M8-a `SqlCipherTokenStore` pattern.
- Event content (title, description, attendee emails) is NOT logged in the activity log (`event_summary` is stored for the owner's audit view — this is intentional owner data, encrypted at rest in SQLCipher).
- `sendUpdates="none"` on auto-path writes (self-only, no one to notify) — avoids spurious Google notification emails.
- The `PendingAction.args` field carries the full bound args dict (re-validated and re-executed on approval via `ActionStagingService.approve` → `ToolRegistry.get_tool(fq_name).callable_ref`). This is owner-private data — `PendingActionStore` is owner-private SQLCipher under the M2 wall (GATE-a Assumptions). No separate verification needed: GATE-a's security section asserts this invariant.

[apex-security review findings resolved: classifier is a single-source-of-truth pure function; no override flag; GATED path never calls execute_fn; respond_to_invite hard-coded first; empty-owner failsafe; key.as_hex() scoped local; event content encrypted in SQLCipher; sendUpdates policy.]

### Performance
Auto-path write-through is synchronous (one Google API call + cache invalidate). Gated path calls `ActionStagingService.stage(...)` which inserts a row into `PendingActionStore` (a local SQLCipher write) and returns immediately — no network round-trip at stage time. The activity log is an append-only INSERT (negligible). The classifier is a pure function — O(n) over the attendee list, typically n < 10.

### Accessibility
(none — no frontend; the Review surface plain-language explanation is M7-b's `explain()`)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/modules/calendar/write_tools.py, gating.py, activity_log.py | Type + docstring all exports; document the classifier rules explicitly (the ordered rule list), the GATED-never-executes invariant, the activity-log SQLCipher pattern, the stage_fn `ActionStagingService.stage(...)` call with module/tool/args/summary contract (ADR-012) |
| Inline | src/artemis/modules/calendar/manifest.py | Document the two-scope registration (read scope from CAL-a + write scope added here) |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_calendar_write.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_calendar_write.py` → verify: classifier truth table passes (all 9 cases); AUTO path calls FakeCalendarClient write method AND activity_log records entry AND FakeActionStagingService.staged is empty; GATED path does NOT call FakeCalendarClient AND FakeActionStagingService.staged has one entry with correct module/tool/args/non-empty summary AND PendingAction.status==PENDING; RSVP always gated; recurrence scope threaded correctly; CalendarWriteError raised on client failure; ScopeLockedError raised on locked ActivityLog; cache.invalidate called on AUTO success.
- [ ] Run `uv run python -c "from artemis.modules.calendar.gating import classify, GateDecision; assert classify('respond_to_invite', [], 'me@x.com') == GateDecision.GATED; assert classify('block_focus_time', ['other@x.com'], 'me@x.com') == GateDecision.AUTO; print('classifier ok')"` → verify: prints `classifier ok`.
- [ ] Run `uv run pytest -q tests/test_calendar_write.py -k manifest` → verify: the manifest-factory test (Task 5) passes — manifest built via `make_calendar_manifest(tools)` with the wired `CalendarWriteTools` fakes has tool count == CAL-a read tools + 11 write tools and all `ToolSpec.name`s are bare (no `.` — B9). (Replaces the former non-runnable `tools=None` `python -c` AC; B8 — manifest built via factory, no `CALENDAR_MANIFEST` constant.)
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Task 7: block_focus_time creates a real Google event + activity log entry; create_event with attendee stages a PendingAction to PendingActionStore + appears at GET /app/actions/pending + ActionStagingService.approve executes the write (PendingAction→APPROVED, Google event created); no event content in logs → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

**✅ COMPLETE 2026-06-24 (Codex `apex-coder`, host-verified).** Tasks 0–6 done; Task 7 on-hardware-GATED (skipped). Baseline green: mypy `--strict` clean (98 files), ruff clean, **367 tests** (+12).

- [x] Task 0 — `ToolSpec.execute_callable_ref` + registry `tool.execute_callable_ref or tool.callable_ref`; 2 registry tests (distinct twin / fallback).
- [x] Task 1 — write-tool args/return schemas + `CalendarWriteError` (+`WriteResult.tool_name`).
- [x] Task 2 — `classify()` (ordered rules, empty-owner fail-closed) + async `dispatch()`.
- [x] Task 3 — `CalendarWriteTools` front-door (classify) + `*_raw` (raw write + cache.invalidate, no log) methods; mapped to live kw-only CalendarClient signatures; `send_updates="none"` on auto-path, `"all"` on attendee changes.
- [x] Task 4 — `ActivityLog` SQLCipher (mirrors `SqlCipherTokenStore`; ScopeLockedError propagates; AUTO-only).
- [x] Task 5 — 11 write ToolSpecs (bare names; 8 gated → `execute_callable_ref=*_raw`, 3 always-auto → none); factory now `make_calendar_manifest(read_tools, write_tools)`; 21 tools total.
- [x] Task 6 — tests: classifier truth table, AUTO executes+logs, GATED stages-only, **B1 regression (approve→raw twin, no re-stage, real registry+staging+store)**, RSVP always gated, recurrence scope, write-failure→CalendarWriteError, locked-store→ScopeLockedError, cache.invalidate(2-arg), manifest shape.

**Decisions / deviations (review in planning):**
| Task | Decision | Reason | Review? |
|------|----------|--------|---------|
| 0 (fork resolution) | R1 seam `ToolSpec.execute_callable_ref` added; contracts.md Seam 2 D1 mechanism pinned | live registry aliased `{tool}_execute` to the front-door → GATE-a approve re-classified attendee events → re-stage loop (2026-06-10 B1). CAL-b is the first external-effect runtime-gated module. | Yes ⚠️ — contract change ratified inline; confirm in next planning review |
| 3 | update/move/cancel resolve existing event from `default_write_calendar` only (args carry no calendar_id) | spec args omit calendar_id for these tools; fails closed (lookup miss → error, never silent AUTO) | Minor — resolve at on-hardware Task 7 |
