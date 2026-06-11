# Sweep 2026-06-10 — Calendar module + GATE action-staging

Reviewer scope: `GATE-a`, `GATE-b`, `CAL-a`, `CAL-b`, `CAL-c`, `CAL-d` (docs/changes/) against
calendar.md, ADR-011, ADR-012, and cross-checked against M1-a, M6-a, M8-a, DR-a, CLIENT-b.

**Counts: BLOCK 12 · UPGRADE 8 · FLAG 12 · RESEARCH 5**

---

## BLOCK

### B1. Approval re-dispatch is an infinite staging loop — gated actions can never execute
**Files:** GATE-a §Task 3 / ADR-012 §3 · CAL-b §Task 3 · CAL-c §Task 2 (`approve_proposal`)
GATE-a `approve()` re-dispatches via `tool_registry.get_tool(action.tool).callable_ref(validated_args)`.
For CAL-b, that callable is the *same* `CalendarWriteTools` method whose first act is to run
`dispatch()` → `classify()`. The attendees are still present, so the classifier returns `GATED` and
calls `stage_fn()` **again** — the owner-approved action never reaches Google; it just stages a new
`PendingAction` (and GATE-a then records `result = StagedResult` and marks the original APPROVED).
CAL-c has the same defect worse: its gated branch stages `"calendar.approve_proposal"` *itself* with
`{proposal_id, google_event_id}`; on owner approval, `approve_proposal` re-enters, re-detects
attendees, re-stages — unbounded recursion of pending actions. No spec defines a bypass (approved-
execution context, internal `_execute`-tool target, or classifier short-circuit). Off-hardware tests
never catch this because CAL-b Task 6 uses a `FakeActionStagingService` spy and never round-trips
approve through the real tool. **Fix required in spec:** stage an internal ungated execute target
(e.g. `calendar.create_event_execute` registered for staging dispatch only), or pass an
approved-context flag the classifier honours. CAL-b Task 7(c) and GATE-a's "execute-once" invariant
are unsatisfiable as written.

### B2. GATE-b calls `ActionStagingService.list_pending()` — GATE-a never defines it
**Files:** GATE-b §Assumptions (claims it "confirmed"), §Task 1 route `get_pending_actions` ·
GATE-a §Task 3
GATE-a's service exposes only `stage / approve / reject / expire_due`; `list_pending()` exists on
`PendingActionStore` (Task 2) only. GATE-b's first assumption asserts
`ActionStagingService.list_pending() -> list[PendingAction]` as a confirmed GATE-a contract — false.
A literal executor builds an endpoint calling a nonexistent method. Fix: add
`ActionStagingService.list_pending()` delegating to `self.store.list_pending()` in GATE-a Task 3
(one line), or have the route call `action_staging.store.list_pending()` (worse — leaks the store).

### B3. GATE-b route snippets are invalid Python (non-default param after defaulted param)
**Files:** GATE-b §Task 1, all three routes
```python
async def get_pending_actions(
    principal: Principal = Depends(require_unlocked),
    request: Request,                      # SyntaxError: non-default after default
) -> list[PendingActionResponse]:
```
DeepSeek copies snippets verbatim → SyntaxError on all three routes. Reorder (`request: Request`
first) or use `Annotated[Principal, Depends(require_unlocked)]`. Note: CLIENT-b's own
`require_unlocked` snippet (§Task line 52) has the same parameter ordering — flag to whoever owns
the CLIENT review.

### B4. CAL-b ↔ CAL-a symbol drift (file, class, field, and method names all differ)
**Files:** CAL-b §Assumptions bullet 1, §Task 3, §Task 6 · CAL-a §Files to Change, §Task 2/3
- CAL-b assumes `modules/calendar/prefs.py` exporting `CalendarPrefs` with
  `owner_email: str`, `default_write_calendar_id: str`. CAL-a creates **`preferences.py`** exporting
  **`CalPrefs`** with `owner_email: str | None` and **`default_write_calendar`**.
- CAL-b's `CalendarWriteTools` takes `cache: CalendarCache` and calls `cache.invalidate(event_id)`.
  CAL-a's class is **`EventCacheStore`** and has **no `invalidate` method** (only
  `upsert/delete/get_sync_token/set_sync_token/query_events/clear_calendar`). Task 6 even asserts on
  a `FakeCalendarCache.invalidate` spy. Either CAL-a must add `invalidate(event_id, calendar_id)`
  (note: its PK is `(event_id, calendar_id)` — single-arg invalidate is also underspecified) or
  CAL-b must use `delete`/re-sync semantics. Amend one side; today both "Stop"-graded assumptions
  are false.

### B5. CalendarClient write methods exist in no spec
**Files:** CAL-b §Assumptions bullet on CAL-a, §Task 3 method mapping · CAL-c §Assumptions bullet 2 ·
CAL-a §Task 1
CAL-a's `CalendarClient` Protocol is read-only (`list_calendars`, `list_events`, `get_event`,
`query_free_busy`). CAL-b's Task 3 maps 9 write methods (`create_event`, `update_event`,
`move_event`, `cancel_event`, `respond_to_invite`, `add_attendees`, `remove_attendees`, `quick_add`,
`set_reminders`) onto the client, but `client.py` is **not in CAL-b's Files to Change** and no task
extends the Protocol, `GoogleCalendarClient`, or `FakeCalendarClient`. CAL-c additionally assumes
`create_event(body) -> dict`, `update_event(event_id, body) -> dict`, `delete_event(event_id) -> None`
— signatures that **contradict CAL-b's** (`create_event(summary, start, end, …, send_updates=…)`),
and `delete_event` appears in neither CAL-a nor CAL-b. Three specs, three incompatible port shapes,
zero owners. A new task (in CAL-b, touching `client.py`) must define the write surface once;
CAL-c must be amended to the same signatures.

### B6. CAL-c ↔ CAL-a/CAL-b interface fictions (`sync`, `is_self_only`, `write_event`)
**Files:** CAL-c §Assumptions bullets 1–2, §Task 3 (`make_change_detection_check`), §Task 2
- CAL-c assumes `modules/calendar/sync.py` exporting `sync(client, cache_store, *, window_months=12)`.
  CAL-a puts sync in **`cache.py`** as **`CalendarSyncEngine.sync(calendar_id, owner_email)`**
  (engine constructed with `(client, store, prefs)`); there is no module-level `sync()` and no
  `sync.py`. The change-detection hook as written cannot be wired, and `SyncResult` (which the hook
  needs for `changed_count`) has different fields (`events_added/updated/deleted`) than assumed.
- CAL-c assumes CAL-b `gating.py` exports `is_self_only(event) -> bool`. CAL-b defines
  `classify(tool_name, attendees, owner_email) -> GateDecision` — no `is_self_only`, different
  inputs (CAL-c would also need owner_email + attendee resolution it never plumbs).
- CAL-c assumes `write_tools.py` exports `write_event(client, event_dict) -> WriteResult`. CAL-b
  defines only `CalendarWriteTools` bound methods.
CAL-c acknowledges "park a clarification at build time" — but all three are *certain* misses, not
risks. Amend CAL-c (or add the seams to CAL-a/b) before build.

### B7. CAL-c tool callables violate the M1-a dispatch contract (breaks GATE-a approve)
**Files:** CAL-c §Task 2, §Task 4 · M1-a §Task (ToolSpec) · GATE-a §Task 3
M1-a: `callable_ref: Callable[..., BaseModel]` — "takes a validated args model, returns a return
model"; GATE-a approve calls `callable_ref(validated_args)` then `result_obj.model_dump()`. CAL-c
registers raw module-level functions like
`approve_proposal(client, store, staging, *, key_provider, proposal_id)` as `callable_ref` with
`args_schema=ApproveRejectArgs` — (a) the single-args-model call shape doesn't match, (b) the
functions return `ProposalRow` (a dataclass — no `model_dump()`, so approve crashes) or
`ProposalRow | PendingAction`, while `return_schema=ProposalResult` claims otherwise. CAL-a solved
this with the `CalendarTools` bound-method pattern; CAL-c must do the same (an `OverlayTools` class
holding `client/store/staging/key_provider`, methods `(args: Model) -> ProposalResult`).

### B8. `CALENDAR_MANIFEST` constant cannot exist — impossible acceptance checks
**Files:** CAL-b §Task 5 done-when + §Acceptance Criteria · CAL-c §Task 4 done-when +
§Acceptance Criteria · CAL-a §Task 5/6
CAL-a deliberately ships only `make_calendar_manifest(tools: CalendarTools)` and states "CAL-a does
NOT auto-register (no global singleton with live credentials)". CAL-b and CAL-c acceptance criteria
both run `from artemis.modules.calendar.manifest import CALENDAR_MANIFEST` — a module-level constant
that would require constructed live dependencies at import time, which CAL-a forbids. Either CAL-a
adds a dependency-free manifest constant (tools constructed lazily) — a design change — or CAL-b/c
acceptance commands must build the manifest via the factory with fakes. As written the checks can
never pass.

### B9. Tool-name double-prefix: CAL-b manifest names break `get_tool("calendar.create_event")`
**Files:** CAL-b §Task 5 table, §Task 6 (activity-log assertions) · CAL-a §Task 5 · M1-a (registry
ids = `f"{manifest.name}.{tool.name}"`)
M1-a composes the fq id from manifest name + bare tool name; CAL-a registers bare names
(`"create_event"`). CAL-b's Task 5 table lists tool names as `calendar.create_event`,
`calendar.block_focus_time`, etc. — a literal executor sets `ToolSpec(name="calendar.create_event")`,
producing registry id `calendar.calendar.create_event`. GATE-a approve then raises `KeyError` on the
staged `tool="calendar.create_event"` and the whole approval chain dies. Amend CAL-b Task 5 to bare
names and state explicitly that `stage(tool=...)` uses the registry fq form.

### B10. `quick_add` executes the external write *before* classification
**Files:** CAL-b §Task 3 mapping (`quick_add`), §Task 3 step 1
The mapping says `client.quick_add(text, calendar_id)` "then fetch the new event to resolve
attendees for the classifier" — the Google write has already happened before the gate runs,
violating the spec's own invariant 2 ("GATED path NEVER calls the write API"). The `dispatch()`
flow (resolve attendees → classify → execute-or-stage) cannot express execute-first, and no
remediation (delete on GATED?) is specified — a literal executor produces either a gate bypass or
undefined behavior. Fix: pre-classify `quick_add` (Google quickAdd does not create attendees from
text — see R4; if confirmed, make it always-AUTO like `block_focus_time`), or drop the tool from
wave-1.

### B11. Incremental sync never sees deletions: `showDeleted` defaults to false
**Files:** CAL-a §Task 1 (`show_deleted: bool = False`), §Task 3 sync step 4
`events.list` with `syncToken` returns cancelled events **only if `showDeleted=true`**; the default
is false. CAL-a's incremental call `client.list_events(calendar_id, sync_token=sync_token)` passes
no `show_deleted`, so the step-4 `status == "cancelled" → store.delete(...)` branch never fires
against the real API — cancelled meetings stay in the cache forever (briefings, free_busy, find_time
all wrong). The fakes hand-deliver cancelled items, so Task 7 passes while the real sync is broken.
Fix: pass `show_deleted=True` on the incremental call (and on the initial call, filtering cancelled
at parse time, since Google requires consistent params across a sync-token sequence — see R2).

### B12. CAL-d wires an `await` into a sync `check_ref`, and the stub call sites it replaces don't exist
**Files:** CAL-d §Task 4 · CAL-c §Task 3 · M6-a §Task 1 (`check_ref: Callable[[], HookResult]`)
M6-a's contract (confirmed in M6-a Task 1/3) is a **synchronous zero-arg** `check_ref`; the Heartbeat
calls `result = hook.check_ref()` inside `tick()`. CAL-d Task 4 step 2 instructs "replace with
`await quarantine_event_text(reader, event)`" inside the check_ref closure — illegal in a sync
callable; no bridging instruction (sync wrapper, `asyncio.run`, or an async hook contract change) is
given. Additionally, CAL-c's payload rules say briefing/prep payloads "MUST contain ONLY event ids
and start times (NOT titles…)" — so the `_quarantine_stub(event_field)` call sites CAL-d says to
replace are never actually built into payload assembly (CAL-c is internally ambiguous here too).
A literal executor finds no call site and no legal place to await. Fix: define a sync facade (e.g.
`quarantine_event_text_sync` running the reader on the hook worker loop) or move quarantine into the
M6-b `needs_llm` render stage, and specify the exact new payload fields (`extract_summary`,
`extract_claims`) the hooks emit.

---

## UPGRADE

### U1. GATE-a approve: dispatch-then-mark gives at-least-once semantics for external effects
**File:** GATE-a §Task 3 (`approve`)
Order is: dispatch `callable_ref` → `set_status(APPROVED, result)`. A crash between the two leaves
the action `PENDING` with the invite already sent; the owner re-approves → double-send. For
unrecoverable external effects, at-most-once is the right failure mode: flip status (or a new
`EXECUTING` state) *before* dispatch via a conditional
`UPDATE pending_actions SET status=? WHERE id=? AND status='pending'` (check rowcount) — this also
makes execute-once robust if the route ever runs in a threadpool (see U7).

### U2. `expire_due` is never wired to anything
**Files:** GATE-a §Task 3 · GATE-b §Task 1 / §Assumptions
No spec schedules `expire_due` (no heartbeat hook, no cron). Consequence: past-`expires_at` rows
stay `status="pending"` and appear in GATE-b's Review list (GATE-b's assumption "EXPIRED rows are
never returned" only holds for rows already *marked* expired). approve's expiry-before-dispatch
check keeps it safe, but the surface shows dead actions. Cheapest fix: `ActionStagingService.
list_pending()` (added per B2) calls `self.expire_due(now)` first; or add a Tier-1 housekeeping hook.

### U3. GATE-b: map `ScopeLockedError` → 423 on approve (TOCTOU), fix the exception name
**File:** GATE-b §Task 1 error mapping
The spec claims "A `VaultLockedError` from `approve` cannot be reached (the route is behind
`require_unlocked`)". (a) The exception is named `ScopeLockedError` everywhere else; (b) the vault
can idle-lock between the dependency check and the synchronous dispatch — `ScopeLockedError` then
surfaces as a 500. Add `except ScopeLockedError: raise HTTPException(423, "vault locked")` to the
approve route, consistent with CLIENT-b's fail-closed posture.

### U4. CAL-a registers the write scope in the read-only spec — least-privilege violation
**Files:** CAL-a §Assumptions (scope bullet), §Task 5 (`register_google_scopes`) · CAL-b §Task 5
CAL-a registers both `calendar.readonly` **and** `calendar.events` (write). Its justification
("`calendar.events` is required for FreeBusy") is wrong — FreeBusy works under `calendar.readonly`
(and a dedicated `calendar.freebusy` scope exists). CAL-b already registers `calendar.events` under
`"calendar_write"`. Drop `calendar.events` from CAL-a so an owner who pauses at CAL-a has granted
read-only access (verify per R1).

### U5. CAL-b: resolve attendees from the cache, not a live `get_event`, and pin email comparison
**File:** CAL-b §Task 3 step 1 · CAL-d §Task 3 step 1
update/move/cancel do a live `client.get_event(event_id)` per write just to read attendees — the
mirror cache (CAL-a `query_events`) already has them; use cache with live fallback (saves a network
round-trip on the security-critical path and works when Google is briefly unreachable). Also: CAL-b
classify lowercases+strips; CAL-d's memory gate compares `a != owner_email` case-sensitively —
define one canonical comparison helper (CAL-b owns it) and reuse.

### U6. CAL-c projection: hardcoded UTC timezone and an attendee-leak ambiguity in `propose_event`
**File:** CAL-c §Task 2 (`_project_to_google`, `propose_event`)
(a) `_project_to_google` hardcodes `"timeZone": "UTC"` — use `prefs.timezone`. (b) `propose_event`
says "the `draft` dict becomes the tentative Google event body" while `_project_to_google` builds
the body from `ProposalRow` fields only — contradictory. If the raw draft is the body, a draft
containing `attendees` projects onto other people's calendars (a tentative event with attendees is
visible to them) — an external effect bypassing the STRICT gate. Specify: the projected body is
constructed **only** from `ProposalRow` fields (which cannot hold attendees), and `propose_event`
must reject/strip `attendees` in `draft`.

### U7. GATE-b approve route blocks the event loop on a synchronous Google write
**File:** GATE-b §Task 1 / §Specialist Performance
`approve` dispatches the bound tool synchronously (~100–300 ms calendar write) inside an
`async def` route → blocks the single-worker event loop (including SSE chat streams). Either make
the three routes plain `def` (FastAPI threadpool) — which then *requires* U1's conditional-update
for execute-once — or wrap dispatch in `run_in_threadpool`. State the choice in the spec.

### U8. `InvalidSyncTokenError` defined in `cache.py` but raised by `client.py` — import cycle
**File:** CAL-a §Task 3 (last paragraph) vs §Task 1
`GoogleCalendarClient` (client.py) must map HTTP 410 → `InvalidSyncTokenError`, which Task 3 defines
in cache.py; cache.py imports the client types → circular import. Move the exception to `client.py`
(the layer that raises it) and have cache.py import it.

---

## FLAG

### F1. GATE-a off-hardware store tests assume `sqlcipher_open` works without SQLCipher
**File:** GATE-a §Task 5 ("a `PendingActionStore` built over a real SQLite file in tmp_path")
CAL-a's Task 7 explicitly assumes SQLCipher may not be importable off-hardware and uses dict shims /
mocks; GATE-a runs the real store through `sqlcipher_open` in CI. The two specs encode opposite
beliefs about M2-c's off-hardware behavior. Resolve once (does M2-c ship a plain-sqlite fallback?)
and align both specs (see R3).

### F2. CAL-b: `owner_email` is `str | None` in prefs but `str` in `classify`; None path unspecified
**Files:** CAL-b §Task 2 (failsafe covers `""` only) · CAL-a §Task 2 (`owner_email: str | None = None`)
Off-hardware/default prefs give `owner_email=None` (CAL-a populates it only in gated Task 8(b)).
`classify` would call `None.lower()` → AttributeError. Specify: `None` or `""` → GATED failsafe, and
where the None→str coercion happens.

### F3. CAL-b assumption credits `/app/actions/*` to "CLIENT-b" — the spec is GATE-b
**File:** CAL-b §Assumptions (CLIENT-b bullet)
A literal pre-flight verifying "CLIENT-b has been extended with `/app/actions/*`" against
CLIENT-b-app-endpoints.md finds nothing. Rename the dependency to GATE-b.

### F4. CAL-c: ntfy templates have no registration mechanism; `delivery` never set
**File:** CAL-c §Task 3 ("Template: f-…" lines) · §Specialist Security (`needs_llm=False` … "Templates
are registered in hooks.py")
The five `needs_llm=False` hooks each show a template f-string but no task/file/API call registers
them with the M6-b `TemplateRegistry` (no function name, no signature). Also no `HookSpec` sets
`delivery` (fine — M6-a defaults `None` — but say so, since CAL-c's own assumption lists `delivery`
as part of the contract). A literal executor will drop the templates on the floor.

### F5. CAL-c tests assert write methods on CAL-a's read-only `FakeCalendarClient`
**File:** CAL-c §Task 5 (Overlay store tests) · CAL-a §Task 1
Tests assert `FakeCalendarClient.update_event` / `delete_event` / `create_event` called — none exist
on CAL-a's fake and no task adds them (corollary of B5; listed separately because even after B5 is
fixed in the real client, the *fake* needs spec'd call-recording behavior).

### F6. CAL-d locked-vault test for the memory path is not runnable as described
**File:** CAL-d §Task 5 ("`CalendarMemoryExtractor.extract` path propagates `ScopeLockedError` from
the `QuarantinedReader` when the underlying store is locked")
`QuarantinedReader` (DR-a) has no store and no key provider — it wraps a `ModelPort`. There is no
defined mechanism by which it raises `ScopeLockedError`. Specify the actual locked failure point
(the `MemoryWriteQueue`/store underneath M4-b) or delete the assertion.

### F7. CAL-d: connector→pipeline routing unspecified
**File:** CAL-d §Task 2
`CalendarKnowledgeConnector` implements the M3-a `Connector` Protocol, but no line registers it with
`IngestPipeline` so that `pipeline.ingest(Source(kind="calendar_meeting", …))` dispatches to it.
Name the registration call (or constructor wiring) explicitly.

### F8. CAL-a: `FakeCalendarClient.set_incremental_events` mentioned but never specified
**File:** CAL-a §Task 1
The incremental add/update/delete test (Task 7) needs it, but its signature/semantics ("configurable
via `set_incremental_events`") are a parenthetical. Give the exact method signature and behavior.

### F9. CAL-d Task 5 "[Pending CAL-c]" marker contradicts its own prerequisites
**File:** CAL-d §Task 5 last bullet vs §Prerequisites
CAL-c is listed as a hard prerequisite, so the render-path test is unconditional — the "when CAL-c
hooks exist" hedge invites a literal executor to skip it. Remove the hedge.

### F10. GATE-a acceptance wording confuses who raises `ScopeLockedError`
**File:** GATE-a §Task 3 done-when / §Acceptance Criteria
"approve with a locked vault (FakeKeyProvider that raises `ScopeLockedError` from `callable_ref`)"
— the FakeKeyProvider doesn't sit inside `callable_ref`; Task 5's version (spy callable raises) is
correct. Align the wording so the executor builds one test, not two contradictory ones.

### F11. GATE-b: `app.state.gateway.tool_registry` attribute path unverified
**File:** GATE-b §Task 2
CLIENT-b's `main.py` stores `gateway` on `app.state`, but no spec confirms the gateway exposes a
public `tool_registry` attribute. Mark it as an assumption with a fallback (construct/import the
registry from the composition root) or verify against M1-c before build.

### F12. Tool-name convention: CAL-a bare vs calendar.md qualified — state the rule once
**Files:** CAL-a §Task 5 (bare names) · calendar.md §A/§B (qualified `calendar.list_events`) ·
CAL-b §Task 5 (qualified — see B9)
The design doc and CAL-b use `calendar.x` while CAL-a and M1-a use bare names + registry-composed
fq ids. After fixing B9, add one sentence to CAL-b/CAL-c: "ToolSpec.name is bare; `module.tool` is
the registry id used by `stage()`/`get_tool()`."

---

## RESEARCH

### R1. Minimal Google scope set for FreeBusy (mid-2026)
Verify whether `calendar.readonly` (or the narrower `calendar.freebusy`) suffices for
`freebusy.query` on owner + attendee calendars, so CAL-a can drop `calendar.events` (U4). Also
confirm current Google verification posture for unverified single-owner apps with calendar scopes
(calendar.md decision "published-unverified" — re-verify it still permits persistent refresh tokens
in 2026).

### R2. `events.list` syncToken parameter-consistency rules
Confirm against current Google Calendar API docs: (a) `showDeleted=true` is required to receive
cancellations on incremental sync (B11); (b) which parameters must be identical between the initial
bounded request and subsequent syncToken requests (CAL-a's initial call passes
`time_min/time_max/show_deleted` — if the incremental call must repeat `show_deleted`, encode that);
(c) 410-GONE full-resync handling (CAL-a's handling looks correct — confirm no `pageToken` edge).

### R3. M2-c `sqlcipher_open` off-hardware behavior
Does M2-c provide a plain-SQLite shim off-hardware, or is the import gated? Determines whether
GATE-a Task 5's real-store CI tests are runnable and whether CAL-a/CAL-c's dict-shim approach should
be the single pattern for all four calendar/GATE SQLCipher stores (F1).

### R4. Google `quickAdd` attendee semantics
Confirm `events.quickAdd` cannot produce attendees from parsed text. If confirmed, reclassify
`quick_add` as always-AUTO (resolving B10 with a one-line classifier rule); if it can, the tool must
be pre-gated or dropped.

### R5. `sendUpdates` default on `events.insert` for tentative projections
CAL-c's `_project_to_google` passes no `send_updates`. Confirm the API default (`none`) and encode
it explicitly anyway — the projection path must never notify anyone (defense in depth for U6b).

---

## Over-engineering review (rubric check 5)

No significant gold-plating found. GATE-a's model/store/service split is the justified minimum;
GATE-b's three thin endpoints match ADR-012 §4; CAL-a's two-store split is defensible. Two minor
notes: (a) CAL-b's `StagedResult` + `WriteResult.status: Literal["executed","staged_for_review"]`
double-encode the same fact — `WriteResult.status` can lose the `"staged_for_review"` arm once
`StagedResult` is the gated return; (b) GATE-a Task 5's "args never contain untrusted text" test
asserts only `isinstance(action.args, dict)` — a tautology (the field is typed `dict`); keep the
docstring contract, drop the no-op assertion.
