---
spec: cal-b-write-gating-activitylog
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CAL-b — Calendar write/management tools + STRICT auto-vs-gated classifier + activity log + Review-staging integration

**Identity:** Adds the §B write-tool surface to the calendar module (create/update/move/cancel/RSVP/attendees/recurring/quick_add/block_focus_time/set_reminders), the STRICT runtime classifier (any attendee ≠ owner → GATED via pending-action staging; self-only → AUTO write-through + activity log), the owned SQLCipher activity log of unattended auto-actions, and the GATE-a `ActionStagingService` integration that stages gated one-off actions as owner-pending `PendingAction` instances (not recipes — see ADR-012).
→ why: see docs/technical/modules/calendar.md §B · docs/technical/adr/ADR-011-spoke-source-of-truth.md (self-only autonomous; external-effect gated) · docs/technical/adr/ADR-012-gated-action-staging.md (pending-action model, distinct from recipe Review).

<!-- Split rule: ONE logical phase (write surface + gating + log + staging). Exceeds 3 files because
     all five pieces form an inseparable gating unit: write tools call the classifier; the classifier
     calls either write-through (→ log) or the GATE-a staging (→ TAKES_ACTION PendingAction). Splitting
     would leave a write tool that calls nothing, or a classifier with no consumers to test the
     invariant. Justified atomic exception, consistent with M8-a / M0-a / M1-a precedents. Flagged per rules. -->

## Assumptions
- **CAL-a** is complete: `modules/calendar/client.py` (`CalendarClient` port + `FakeCalendarClient`), `modules/calendar/manifest.py` (module manifest with read tools), `modules/calendar/cache.py` (read-cache + `invalidate(event_id)`), `modules/calendar/prefs.py` (`CalendarPrefs` with `owner_email: str`, `default_write_calendar_id: str`). CAL-b modifies `manifest.py` and calls `CalendarClient` + `cache.invalidate`. → impact: Stop (these exact symbols are required; verify names match CAL-a before executing).
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
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/modules/calendar/write_tools.py | create | §B ToolSpec definitions, typed args/return schemas, action_risk baselines |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/gating.py | create | runtime classifier `classify()`, stage-vs-execute dispatch `dispatch()`, `AUTO`/`GATED` enum |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/activity_log.py | create | SQLCipher append-only activity log of auto-actions |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py | modify | add write ToolSpecs to the existing manifest (CAL-a created it) |
| /Users/artemis-build/artemis/tests/test_calendar_write.py | create | classifier truth table, AUTO executes+logs, GATED stages-only, recurrence, write-failure, locked-store |

## Tasks

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
  2. `tool_name in {"block_focus_time", "set_reminders"}` → `AUTO` (always; self-only by design)
  3. `non_owner = [e for e in attendees if e.lower().strip() != owner_email.lower().strip()]` → if `len(non_owner) > 0` → `GATED`
  4. `else` → `AUTO`

  Failsafe: if `owner_email` is empty string → treat as having attendees → `GATED` (fail-safe; never auto-write when identity is unknown).

  ```python
  def dispatch(
      tool_name: str,
      event_id: str | None,
      attendees: list[str],
      owner_email: str,
      *,
      execute_fn: Callable[[], WriteResult],
      stage_fn: Callable[[], StagedResult],
      log_fn: Callable[[WriteResult], None],
  ) -> WriteResult | StagedResult:
  ```

  Logic: `decision = classify(tool_name, attendees, owner_email)`. If `AUTO`: result = `execute_fn()`; `log_fn(result)`; return result. If `GATED`: return `stage_fn()` (do NOT call `execute_fn`).

  Done when: `uv run mypy --strict src` passes; truth table verified in tests (Task 6).

- [ ] Task 3: Implement the §B write tools — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/write_tools.py` (same file as Task 1, additive) —

  `class CalendarWriteTools` constructed with `(client: CalendarClient, cache: CalendarCache, prefs: CalendarPrefs, staging: ActionStagingService, activity_log: "ActivityLog")`. One method per §B tool. Each method:
  1. Resolves attendees from args or (for update/move/cancel) fetches the existing event via `client.get_event(event_id)` to read its `attendees` field.
  2. Calls `dispatch(tool_name, event_id, attendees, prefs.owner_email, execute_fn=..., stage_fn=..., log_fn=activity_log.record)`.
  3. The `execute_fn` calls the appropriate `CalendarClient` method (see below), then calls `cache.invalidate(event_id)` on success. On `CalendarClient` error, raises `CalendarWriteError`.
  4. The `stage_fn` calls `staging.stage(module="calendar", tool=f"calendar.{tool_name}", args=args.model_dump(), summary=<plain-language description of the external effect>)`. The summary must be deterministic and human-readable (e.g. `"Cancel event 'Team sync' — has attendees Alice, Bob; pending owner approval"`). Returns `StagedResult(pending_action_id=action.id, summary=action.summary)` where `action` is the returned `PendingAction`. Does NOT execute the Google write — the action is now PENDING; the owner approves it via the Review screen → GATE-b → `ActionStagingService.approve` re-dispatches the calendar write tool via `ToolRegistry`.

  **CalendarClient method mapping** (one call per tool in `execute_fn`):
  - `create_event(args)` → `client.create_event(summary, start, end, description, location, attendees, calendar_id, recurrence, reminders, send_updates="all")`
  - `update_event(args)` → `client.update_event(event_id, changes_dict, recurrence_scope, send_updates="all")`
  - `move_event(args)` → `client.move_event(event_id, new_start, new_end, recurrence_scope, send_updates="all")`
  - `cancel_event(args)` → `client.cancel_event(event_id, recurrence_scope, send_updates="all")`
  - `respond_to_invite(args)` → `client.respond_to_invite(event_id, response)` (always gated; this line is the gated-path execute_fn — only runs after owner approval)
  - `add_attendees(args)` → `client.add_attendees(event_id, attendee_emails, send_updates="all")`
  - `remove_attendees(args)` → `client.remove_attendees(event_id, attendee_emails, send_updates="all")`
  - `create_recurring_event(args)` → `client.create_event(...)` with `recurrence=[args.rrule]`
  - `quick_add(args)` → `client.quick_add(text, calendar_id)` then fetch the new event to resolve attendees for the classifier
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

- [ ] Task 5: Add write ToolSpecs to the manifest — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` (modify, additive only) —

  For each §B tool add a `ToolSpec` to the manifest's `tools` list. Exact `action_risk` baselines (the runtime classifier is the real gate; these are hint-only):

  | tool_name | action_risk baseline |
  |---|---|
  | `calendar.block_focus_time` | `ActionRisk.WRITE` |
  | `calendar.create_event` | `ActionRisk.HIGH_STAKES` |
  | `calendar.update_event` | `ActionRisk.HIGH_STAKES` |
  | `calendar.move_event` | `ActionRisk.HIGH_STAKES` |
  | `calendar.cancel_event` | `ActionRisk.HIGH_STAKES` |
  | `calendar.respond_to_invite` | `ActionRisk.HIGH_STAKES` |
  | `calendar.add_attendees` | `ActionRisk.HIGH_STAKES` |
  | `calendar.remove_attendees` | `ActionRisk.HIGH_STAKES` |
  | `calendar.create_recurring_event` | `ActionRisk.HIGH_STAKES` |
  | `calendar.quick_add` | `ActionRisk.HIGH_STAKES` |
  | `calendar.set_reminders` | `ActionRisk.WRITE` |

  Each `ToolSpec` uses the corresponding `Args` and `Return` schema from `write_tools.py`. The `callable_ref` points to the matching `CalendarWriteTools` method (bound method reference; the manifest is constructed with a `CalendarWriteTools` instance by the module factory). Register scopes at module import: `register_google_scopes("calendar_write", {"https://www.googleapis.com/auth/calendar.events"})`.

  Done when: `uv run mypy --strict src` passes; `from artemis.modules.calendar.manifest import CALENDAR_MANIFEST` shows 11 additional tools (verify count vs CAL-a read tools).

- [ ] Task 6: Write tests (off-hardware, fakes only) — files: `/Users/artemis-build/artemis/tests/test_calendar_write.py` —

  Typed pytest. Fixtures: `FakeCalendarClient` (from CAL-a), `FakeKeyProvider`, `FakeActionStagingService` (in-test spy; records all `stage(module, tool, args, summary, ...)` calls and returns a minimal `PendingAction(id="fake-id-...", module=module, tool=tool, args=args, summary=summary, action_class="takes-action", status=ActionStatus.PENDING, created_at=..., expires_at=...)`; also exposes `.staged: list[PendingAction]` for assertions), `ActivityLog` over `tmp_path` with unlocked `FakeKeyProvider`, `CalendarWriteTools` instance wiring all fakes.

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

  **RSVP always gated:**
  - `respond_to_invite(RespondToInviteArgs(event_id="e1", response="accepted"))` → `FakeCalendarClient.respond_to_invite` NOT called; `FakeActionStagingService.staged` has exactly one entry with `tool == "calendar.respond_to_invite"` and `summary` non-empty.

  **Recurrence scopes (AUTO path):**
  - `cancel_event(CancelEventArgs(event_id="e1", recurrence_scope="THIS_AND_FOLLOWING"))` on a self-only event → `FakeCalendarClient.cancel_event` called with `recurrence_scope="THIS_AND_FOLLOWING"`.

  **Write failure surfaces:**
  - When `FakeCalendarClient.create_event` raises, `block_focus_time` raises `CalendarWriteError` (not silently dropped). Activity log entry is NOT written (write failed before log).

  **Locked store — ScopeLockedError:**
  - `ActivityLog(settings, FakeKeyProvider(owner_unlocked=False)).record(...)` raises `ScopeLockedError`.

  **Cache invalidation:**
  - After an AUTO `update_event`, `FakeCalendarCache.invalidate` was called with the event_id.

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
- [ ] Run `uv run python -c "from artemis.modules.calendar.manifest import CALENDAR_MANIFEST; write_tools = [t for t in CALENDAR_MANIFEST.tools if 'focus' in t.name or 'create' in t.name or 'cancel' in t.name]; print(len(CALENDAR_MANIFEST.tools))"` → verify: total tool count equals CAL-a read tools + 11 write tools.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Task 7: block_focus_time creates a real Google event + activity log entry; create_event with attendee stages a PendingAction to PendingActionStore + appears at GET /app/actions/pending + ActionStagingService.approve executes the write (PendingAction→APPROVED, Google event created); no event content in logs → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
