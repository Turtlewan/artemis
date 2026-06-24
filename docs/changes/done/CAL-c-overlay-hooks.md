---
spec: cal-c-overlay-hooks
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seams 2, 3, 4) + cal-gate.md BLOCKs B1, B6, B7, B8, B9, F12 -->

# Spec: CAL-c — Proposal/hold overlay (+ Google tentative projection lifecycle) + proactive hooks

**Identity:** Builds the Artemis-native proposal/hold overlay (propose_reschedule/propose_event/hold_tentative/list_proposals/approve_proposal/reject_proposal with Google tentative projection + marker lifecycle), the §D proactive hooks (daily briefing, upcoming-event reminder, change-detection sync, conflict alert, free-gap focus-protect, unanswered-invite nudge, prep nudge) on the M6 Heartbeat (Tier-1), and wires them into the calendar `ModuleManifest`.
→ why: see docs/technical/modules/calendar.md §C,§D · docs/technical/adr/ADR-011-spoke-source-of-truth.md (mirror+write-through+native overlay) · docs/technical/adr/ADR-006-two-tier-proactivity.md (Tier-1 hooks queued while locked).

## Assumptions
- CAL-a complete: `src/artemis/modules/calendar/client.py` exports `CalendarClient` port + `FakeCalendarClient`; sync lives in **`src/artemis/modules/calendar/cache.py`** as `CalendarSyncEngine.sync(calendar_id, owner_email) -> SyncResult` (NOT a module-level `sync()` in a `sync.py` — B6 fix); `SyncResult` has fields `events_added`, `events_updated`, `events_deleted`, `full_sync`; `manifest.py` defines `ModuleManifest` for `"calendar"` with `data_scope=DataScope.OWNER_PRIVATE`; the sync engine marks events with `externally_authored: bool` and recognises `extendedProperties.private.artemis_overlay=<proposal_id>` as an own-projection. For the `make_change_detection_check` hook, call `CalendarSyncEngine.sync(calendar_id, owner_email)` directly (construct a `CalendarSyncEngine(client, store, prefs)` instance at hook-factory time and call `.sync()`). **The change_count for `HookResult` is `result.events_added + result.events_updated + result.events_deleted`.** → impact: Stop.
- CAL-b complete: `src/artemis/modules/calendar/gating.py` exports **`classify(tool_name: str, attendees: list[str], owner_email: str) -> GateDecision`** (NOT `is_self_only(event) -> bool` — B6 fix; use `classify("create_event", attendees, prefs.owner_email) == GateDecision.AUTO` to determine self-only); `src/artemis/modules/calendar/write_tools.py` exports `CalendarWriteTools` bound methods (NOT a module-level `write_event(client, event_dict)` — B6 fix); the `CalendarClient` port exposes the canonical Seam 4 write methods: `create_event(*, summary, start, end, ...)`, `update_event(event_id, changes, *, recurrence_scope, ...)`, `cancel_event(event_id, *, recurrence_scope, ...)` — **NO `delete_event`** (use `cancel_event`; Seam 4). → impact: Stop.
- M6-a complete with extended `HookSpec`: `src/artemis/manifest.py` exports `HookSpec(name, interval_seconds|cron, urgency, needs_llm, tier, dedup_key, delivery, check_ref: Callable[[], HookResult])` where `HookResult` is from `artemis.proactive.hook_types`; `ModuleManifest` validator enforces `OWNER_PRIVATE ⇒ tier==1`. → impact: Stop (all calendar hooks declare `tier=1`; the M6-a validator will enforce that against `data_scope=OWNER_PRIVATE`; symbol names must match exactly).
- M8-a complete: `GoogleCredentialsFactory.authorized_credentials()` and `register_google_scopes` available from `artemis.integrations.google`; `ReauthRequiredError` propagates without crashing a hook. → impact: Stop (the overlay's Google projection + approve/reject uses the authorized client; on `ReauthRequiredError` the hook degrades gracefully, never crashes).
- M2 storage primitives complete: `sqlcipher_open`, `KeyProvider.dek_for_scope(OWNER_PRIVATE)`, `ScopeLockedError`, `paths.scope_dir(settings, OWNER_PRIVATE)` all available. → impact: Stop (the overlay store follows the exact `SqlCipherTokenStore` pattern from M8-a).
- `src/artemis/modules/calendar/` is the confirmed package path (consistent with CAL-b's Files-to-Change table and CAL-shared §Module identity; M1-d layout reconciliation is on-hardware only — same one-line deferral as M8-a). All created/modified files use this path prefix.
- GATE-a complete: `ActionStagingService` from `artemis.staging` exports `stage(module: str, tool: str, args: dict[str, object], summary: str, *, ttl: timedelta | None = None) -> PendingAction`; `PendingAction`, `PendingActionStore`, `ActionStatus` re-exported from `artemis.staging`. CAL-c's `approve_proposal` (attendee case) calls `staging.stage("calendar", "calendar.create_event", args_dict, summary)` to record the action as PENDING rather than executing immediately (ADR-012 §3). → impact: Stop (this replaces the previously guessed `artemis.review.stage_for_review`; the M7-b RecipeStore path is NOT used for one-off action instances — see ADR-012 §1).
- The CAL-d `quarantine_event_text` helper (over DR-a `artemis.untrusted`) is NOT yet built. Any hook that would compose externally-authored event text into an LLM prompt (prep nudge, daily briefing event titles) MUST defer that composition: ship the hook with a `_quarantine_stub(text) -> str` shim that returns a sanitised placeholder (`"[external content pending quarantine]"`) and documents the TODO. Do NOT block CAL-c on DR-a/CAL-d.

Simplicity check: Considered splitting overlay and hooks into separate specs — rejected because the overlay's `hold_tentative` emits proposals that the free-gap hook also emits, and the test suite validates both paths together; the brief treats them as one atomic concern. Considered building a full Google Calendar push webhook for change detection — rejected; CAL-shared decision 8 mandates polling via `syncToken`; the change-detection hook calls CAL-a's `sync()`.

## Prerequisites
- Specs complete: **CAL-a** (CalendarClient port, sync engine, read-cache, manifest skeleton), **CAL-b** (write tools, attendee gate, activity log, `is_self_only` + `write_event` seams), **GATE-a** (PendingActionStore + ActionStagingService — required for the attendee-branch of `approve_proposal`), **M6-a** (extended HookSpec/HookResult contract), **M6-b** (HitHandler + on_hits seam), **M6-c** (NtfyDelivery sink), **M8-a** (GoogleCredentialsFactory), **M2-b/M2-c** (KeyProvider/sqlcipher_open). M7-b is NOT a prerequisite for this spec; one-off action staging goes through GATE-a's `ActionStagingService`, not through the recipe ReviewSurface (ADR-012 §1).
- Environment: no new dependencies beyond those added by CAL-a/b + M6/M8-a. Off-hardware fully testable via `FakeCalendarClient` + `FakeKeyProvider` + fake stores + `FakeModelPort`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/overlay.py` | create | Overlay SQLCipher store + ProposalRow model + propose_reschedule/propose_event/hold_tentative/list_proposals/approve_proposal/reject_proposal + Google tentative projection lifecycle |
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/hooks.py` | create | Seven §D HookSpec factories + their check_ref implementations; intentions-projection stub |
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` | modify | Add proposal tools + proactive_hooks list to the existing ModuleManifest |
| `/Users/artemis-build/artemis/tests/test_calendar_overlay_hooks.py` | create | Off-hardware tests: projection lifecycle, marker reconciliation, hook firing, Tier-1 queueing, intentions stub |

## Tasks

- [ ] Task 1: Overlay SQLCipher store + ProposalRow model — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/overlay.py` — create the `OverlayStore` backed by SQLCipher at `paths.scope_dir(settings, OWNER_PRIVATE) / "calendar" / "overlay.db"`. Follow the exact `SqlCipherTokenStore._connect()` pattern from M8-a: `key = key_provider.dek_for_scope(OWNER_PRIVATE)` (raises `ScopeLockedError` if locked → propagates), `conn = sqlcipher_open(path, key.as_hex())` (assign `key.as_hex()` ONLY to a local variable in `_connect()`; never to an instance attribute). Schema:
  ```sql
  CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,           -- uuid4 string
    kind TEXT NOT NULL,            -- "reschedule" | "event" | "hold"
    status TEXT NOT NULL,          -- "pending" | "approved" | "rejected"
    label TEXT NOT NULL,           -- display label
    proposed_start TEXT,           -- ISO-8601 or NULL for holds without a time
    proposed_end TEXT,
    source_event_id TEXT,          -- for reschedule: the Google event id
    google_event_id TEXT,          -- the projected tentative Google event id (NULL until projected)
    created_at TEXT NOT NULL,      -- ISO-8601 UTC
    updated_at TEXT NOT NULL
  )
  ```
  Define `@dataclass(frozen=True) class ProposalRow` with the same fields. Methods on `OverlayStore`: `save(row: ProposalRow) -> None` (upsert), `get(proposal_id: str) -> ProposalRow | None`, `list_pending() -> list[ProposalRow]`, `mark_approved(proposal_id: str, *, updated_at: str) -> None`, `mark_rejected(proposal_id: str, *, updated_at: str) -> None`, `set_google_event_id(proposal_id: str, google_event_id: str, *, updated_at: str) -> None`. **`ScopeLockedError` propagates on every method** (no unlock = no overlay access). — done when: `uv run mypy --strict src` passes; `FakeKeyProvider(owner_unlocked=False)` raises `ScopeLockedError` on `list_pending()`; an `OverlayStore` pointed at a temp dir creates the table on first connect; a `ProposalRow` round-trips through `save`+`get`.

- [ ] Task 2: Proposal overlay public API + Google tentative projection lifecycle — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/overlay.py` (same file) — implement the six proposal tools as module-level functions that take `(client: CalendarClient, store: OverlayStore, *, key_provider: KeyProvider)` plus tool-specific args:

  **`propose_reschedule(client, store, *, key_provider, event_id: str, suggested_start: str, suggested_end: str, reason: str) -> ProposalRow`**: generate a uuid4 `proposal_id`; create a `ProposalRow(kind="reschedule", status="pending", label=f"Reschedule: {event_id}", proposed_start=suggested_start, proposed_end=suggested_end, source_event_id=event_id, google_event_id=None, ...)`; call `_project_to_google(client, proposal_id, row)` to write a Google tentative event (see below); `store.save(row_with_google_id)`; return the row.

  **`propose_event(client, store, *, key_provider, draft: dict) -> ProposalRow`**: same pattern with `kind="event"`; the `draft` dict becomes the tentative Google event body.

  **`hold_tentative(client, store, *, key_provider, start: str, end: str, label: str) -> ProposalRow`**: `kind="hold"`; project to Google as tentative immediately (holds are self-only → auto write-through, consistent with CAL-shared decision 3).

  **`_project_to_google(client: CalendarClient, proposal_id: str, row: ProposalRow) -> str`**: call `client.create_event(summary=row.label, start=row.proposed_start, end=row.proposed_end, calendar_id="primary", description=None, location=None, attendees=(), recurrence=(), reminders=None, send_updates="none")` (B6 / Seam 4: use the canonical keyword-arg signature, NOT a raw dict body; `send_updates="none"` so projection never notifies anyone — U6b). Set `extendedProperties` by patching the returned event via `update_event` or by using the `extendedProperties` param if M1-a's client supports it — whichever is available; document the approach. Return the Google event id from the response dict. Wrap in `try/except ReauthRequiredError: raise` (propagates) + `except Exception as exc: raise OverlayProjectionError(str(exc)) from exc`. Define `class OverlayProjectionError(Exception)`.

  **`list_proposals(store: OverlayStore) -> list[ProposalRow]`**: return `store.list_pending()`.

  **`approve_proposal(client, store, staging: ActionStagingService, *, key_provider, proposal_id: str, owner_email: str) -> ProposalRow`**: load the row; raise `ProposalNotFoundError` if absent or not pending.

  Determine whether the underlying event is self-only using `classify` from CAL-b's `src/artemis/modules/calendar/gating.py` (B6 fix — NOT `is_self_only`):
  - Resolve attendees: for `propose_reschedule` rows, load the source event from the overlay store or cache and read its attendees. For `propose_event`/`hold_tentative`, attendees are empty by design.
  - `decision = classify("approve_proposal", attendees, owner_email)` — `GateDecision.AUTO` if self-only, `GateDecision.GATED` if has non-owner attendees.
  - **Self-only (AUTO path):** `hold_tentative`/`propose_event` rows always take this path; `propose_reschedule` rows where the source event had no non-owner attendees also take this path. Promote the Google tentative event to confirmed: `client.update_event(row.google_event_id, {"status": "confirmed"}, recurrence_scope="THIS_EVENT", send_updates="none")` (B6 / Seam 4: canonical kwargs, not a raw dict body). If `row.google_event_id` is None (projection failed earlier), use a `CalendarWriteTools` instance bound with `client` to create the real event directly.
  - **Attendee case (GATED path) — B1 fix:** if non-owner attendees present, do NOT stage `"calendar.approve_proposal"` itself (that caused the infinite-staging loop — B1). Instead, stage the **underlying write action** that the proposal represents: e.g. for a reschedule, stage `"calendar.update_event"` with the target args; for a `propose_event`, stage `"calendar.create_event"`. The `stage(tool=...)` argument uses the **front-door fq id** (e.g. `"calendar.create_event"`); GATE-a's `approve()` will dispatch the `_execute` twin. Return the original row unchanged with a `StagedResult` indicator.

  After a successful self-only write: `store.mark_approved(proposal_id, updated_at=now_utc())` and return the updated row. For the gated (staged) path, do NOT call `mark_approved` — the row stays `pending` until the staged action is approved. Return type: `ProposalRow` (self-only) or `PendingAction` (gated); document the two cases clearly.

  **`reject_proposal(client, store, *, key_provider, proposal_id: str) -> ProposalRow`**: load the row; if `row.google_event_id` is set, `client.cancel_event(row.google_event_id, recurrence_scope="THIS_EVENT", send_updates="none")` (Seam 4 / B5: use `cancel_event` NOT `delete_event` — `delete_event` does not exist in the canonical CalendarClient Protocol). `store.mark_rejected(proposal_id, updated_at=now_utc())`; return updated row.

  Define `class ProposalNotFoundError(Exception)`. Helper `now_utc() -> str` = `datetime.now(timezone.utc).isoformat()`.

  — done when: `uv run mypy --strict src` passes; `hold_tentative` with `FakeCalendarClient` creates a tentative event with `extendedProperties.private.artemis_overlay == proposal_id`; `approve_proposal` updates that event to `status="confirmed"`; `reject_proposal` calls `cancel_event(row.google_event_id, recurrence_scope="THIS_EVENT", send_updates="none")`; a locked `key_provider` raises `ScopeLockedError` before any Google call.

- [ ] Task 3: Proactive hook factories (§D) — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/hooks.py` — define seven hook factories, each returning a `(check_ref: Callable[[], HookResult], hook_spec_kwargs: dict)` pair, then assemble them into `HookSpec` instances. All hooks have `tier=1` (calendar `data_scope=OWNER_PRIVATE`). Import `HookResult` from `artemis.proactive.hook_types`. Use `FakeCalendarClient` as the type for `client` param in tests.

  **`make_daily_briefing_check(cache_store: CacheStore) -> Callable[[], HookResult]`**: reads today's events from the cache (no Google call); returns `HookResult.of({"event_count": n, "events": [...]}, dedup_value=today.isoformat())` if n > 0 else `HookResult.miss()`. `HookSpec(name="cal_daily_briefing", cron="30 7 * * *", urgency="normal", needs_llm=True, tier=1, dedup_key="cal_briefing", check_ref=<fn>)`. **LLM safety note**: this hook is `needs_llm=True`; the M6-b `HitHandler` will render its payload via the batched LLM call. The `events` list in the payload MUST contain ONLY event ids and start times (NOT titles, descriptions, or attendee names from externally-authored events). Full event text rendering awaits CAL-d's `quarantine_event_text`. Use `_quarantine_stub(title: str) -> str` = `lambda t: "[external content pending quarantine]"` for any external title that would reach the LLM payload. Document: `# TODO(CAL-d): replace _quarantine_stub with quarantine_event_text once DR-a/CAL-d lands`.

  **`make_upcoming_reminder_check(cache_store: CacheStore, *, lookahead_minutes: int = 15) -> Callable[[], HookResult]`**: finds the next event starting within `lookahead_minutes`; returns `HookResult.of({"event_id": id, "starts_in_minutes": n}, dedup_value=event_id)` if found else `HookResult.miss()`. `HookSpec(name="cal_upcoming_reminder", interval_seconds=300, urgency="high", needs_llm=False, tier=1, dedup_key="cal_upcoming", check_ref=<fn>)`. Template: `f"Your event starts in {result.payload['starts_in_minutes']} min"`.

  **`make_change_detection_check(sync_engine: CalendarSyncEngine, calendar_ids: list[str], owner_email: str) -> Callable[[], HookResult]`** (B6 fix: no module-level `sync()` in `sync.py`; use `CalendarSyncEngine` from `cache.py`): calls `sync_engine.sync(calendar_id, owner_email)` for each `calendar_id`; accumulates `changed_count = sum(r.events_added + r.events_updated + r.events_deleted for r in results)` (B6 fix: `SyncResult` fields are `events_added/updated/deleted`, not `changed_count`); returns `HookResult.of({"changed_count": changed_count}, dedup_value=f"{today.isoformat()}-{changed_count}")` if `changed_count > 0` else `HookResult.miss()`. `HookSpec(name="cal_change_detection", interval_seconds=300, urgency="normal", needs_llm=False, tier=1, dedup_key="cal_changes", check_ref=<fn>)`. Template: `f"{result.payload['changed_count']} calendar change(s) detected"`.

  **`make_conflict_alert_check(cache_store: CacheStore) -> Callable[[], HookResult]`**: inspects the cache for overlapping events in the next 24h; returns `HookResult.of({"conflict_count": n, "event_ids": [...]}, dedup_value=f"{today.isoformat()}-{n}")` if conflicts exist else `HookResult.miss()`. `HookSpec(name="cal_conflict_alert", interval_seconds=1800, urgency="high", needs_llm=False, tier=1, dedup_key="cal_conflicts", check_ref=<fn>)`. Template: `f"{result.payload['conflict_count']} scheduling conflict(s) detected"`.

  **`make_free_gap_check(cache_store: CacheStore, overlay_store: OverlayStore, *, min_gap_minutes: int = 30) -> Callable[[], HookResult]`**: finds free gaps ≥ `min_gap_minutes` within working hours today; emits a proposal via `hold_tentative` only if ≥1 gap found AND no pending hold already exists for today (dedup via `overlay_store.list_pending()` filtered to `kind=="hold"` and `proposed_start` today). Returns `HookResult.of({"gap_count": n, "proposal_id": pid}, dedup_value=f"{today.isoformat()}-gap")` if a new hold was emitted else `HookResult.miss()`. `HookSpec(name="cal_free_gap", interval_seconds=3600, urgency="low", needs_llm=False, tier=1, dedup_key="cal_free_gap", check_ref=<fn>)`. Template: `f"Free gap found — focus-block proposal created"`.

  **`make_unanswered_invite_check(cache_store: CacheStore, *, owner_email: str) -> Callable[[], HookResult]`**: finds events where the owner's RSVP status is `needsAction`; returns `HookResult.of({"invite_count": n, "event_ids": [...]}, dedup_value=f"{today.isoformat()}-{n}")` if n > 0 else `HookResult.miss()`. `HookSpec(name="cal_unanswered_invite", interval_seconds=3600, urgency="normal", needs_llm=False, tier=1, dedup_key="cal_invites", check_ref=<fn>)`. Template: `f"{result.payload['invite_count']} invite(s) awaiting your response"`.

  **`make_prep_nudge_check(cache_store: CacheStore, *, lookahead_hours: int = 18) -> Callable[[], HookResult]`**: finds events starting within `lookahead_hours` that the owner organised or was invited to (meetings, not self-only holds); returns `HookResult.of({"event_id": id, "starts_in_hours": h}, dedup_value=event_id)` if found else `HookResult.miss()`. `needs_llm=True` so M6-b renders the nudge text via the batched LLM call. Payload MUST contain ONLY `event_id` and `starts_in_hours` — NOT titles, descriptions, or attendee names from externally-authored fields (same `_quarantine_stub` guard as daily briefing; TODO(CAL-d)). `HookSpec(name="cal_prep_nudge", interval_seconds=3600, urgency="normal", needs_llm=True, tier=1, dedup_key="cal_prep", check_ref=<fn>)`.

  **Intentions projection stub**: define `def _intentions_projection_stub() -> None: pass  # TODO: wire Productivity module when available`. Register as a comment in `hooks.py` — do NOT add a HookSpec for it (it has no `check_ref` to call yet). Document: "Intentions projection deferred until Productivity module exists."

  — done when: `uv run mypy --strict src` passes; each `make_*_check` returns a callable; calling each check against a `FakeCalendarClient` populated with test data returns either `HookResult.miss()` or a `HookResult` with `hit=True`; all HookSpecs have `tier=1`.

- [ ] Task 4: Wire manifest — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` (modify) — add proposal `ToolSpec`s and the `proactive_hooks` list to the existing `ModuleManifest` created by CAL-a. SURGICAL: touch ONLY the `tools` list and `proactive_hooks` list; do NOT change the manifest name, version, description, data_scope, or permissions.

  **B9 / F12 / Seam 2 — ToolSpec.name is BARE.** `ToolSpec.name` is the bare name (e.g. `"propose_reschedule"`), NOT the qualified form. The registry composes the fq id as `"calendar.propose_reschedule"`. **`ToolSpec.name` is bare; `module.tool` is the registry id used by `stage()`/`get_tool()`.**

  **B7 / Seam 2 — callable_ref bound-method pattern.** Module-level functions like `approve_proposal(client, store, staging, *, key_provider, proposal_id)` cannot be registered as `callable_ref` because: (a) the M1-a contract is `callable_ref: Callable[..., Awaitable[BaseModel]]` (ADR-016: async) — an `async def` taking one validated args model, returning a Pydantic result model so `result.model_dump()` works; (b) GATE-a's approve calls `await callable_ref(validated_args)` — single-arg. **Fix:** define an `OverlayTools` class constructed with `(client: CalendarClient, store: OverlayStore, staging: ActionStagingService, key_provider: KeyProvider, prefs: CalPrefs)`. Methods take a single args-model arg and return a `ProposalResult` (Pydantic BaseModel):
  ```python
  class OverlayTools:
      def __init__(self, client, store, staging, key_provider, prefs): ...
      async def propose_reschedule(self, args: ProposeRescheduleArgs) -> ProposalResult: ...
      async def propose_event(self, args: ProposeEventArgs) -> ProposalResult: ...
      async def hold_tentative(self, args: HoldTentativeArgs) -> ProposalResult: ...
      async def list_proposals(self, args: ListProposalsArgs) -> ProposalListResult: ...
      async def approve_proposal(self, args: ApproveRejectArgs) -> ProposalResult: ...
      async def reject_proposal(self, args: ApproveRejectArgs) -> ProposalResult: ...
  ```
  **ADR-016 (uniform async tool-dispatch):** every `OverlayTools` method is `async def` — each is a `ToolSpec.callable_ref` dispatched via `await spec.callable_ref(args)` (Brain) / `await ...callable_ref(validated_args)` (GATE-a approve). Each method delegates to the module-level function (Task 2), injecting `self.client/store/staging/key_provider/prefs`. The module-level functions (`propose_reschedule`, `_project_to_google`, `approve_proposal`, `reject_proposal`, …) stay plain sync `def` — they are NOT `callable_ref`s and call only sync Seam-4 `CalendarClient` methods, sync `OverlayStore` (SQLCipher), and sync `staging.stage` (Seam 3); the `async def` method bodies await nothing extra. `ProposalResult` must be a Pydantic `BaseModel` (not a dataclass) so `result.model_dump()` works in GATE-a.

  > **Hooks are unaffected:** `HookSpec.check_ref` is **synchronous** (Seam 5) and is NOT a tool callable — the seven hook `check_ref`s in Task 3 stay sync `def`. ADR-016 touches only `ToolSpec.callable_ref`.

  Add six `ToolSpec` entries to `tools` (passed via a `make_calendar_overlay_manifest(overlay_tools: OverlayTools) -> list[ToolSpec]` factory — consistent with CAL-a's `make_calendar_manifest` pattern; B8: no import-time `CALENDAR_MANIFEST` constant):
  - `ToolSpec(name="propose_reschedule", ..., callable_ref=overlay_tools.propose_reschedule, ...)`
  - `ToolSpec(name="propose_event", ..., callable_ref=overlay_tools.propose_event, ...)`
  - `ToolSpec(name="hold_tentative", ..., callable_ref=overlay_tools.hold_tentative, ...)`
  - `ToolSpec(name="list_proposals", ..., callable_ref=overlay_tools.list_proposals, action_risk=ActionRisk.READ)`
  - `ToolSpec(name="approve_proposal", ..., callable_ref=overlay_tools.approve_proposal, action_risk=ActionRisk.HIGH_STAKES)`
  - `ToolSpec(name="reject_proposal", ..., callable_ref=overlay_tools.reject_proposal, action_risk=ActionRisk.WRITE)`

  Define simple Pydantic arg/return models in `manifest.py` (or `schemas.py`): `ProposeRescheduleArgs(event_id: str, suggested_start: str, suggested_end: str, reason: str)`, `ProposeEventArgs(draft: dict)`, `HoldTentativeArgs(start: str, end: str, label: str)`, `ListProposalsArgs()`, `ApproveRejectArgs(proposal_id: str)`, `ProposalResult(proposal_id: str, status: str, google_event_id: str | None)` — **Pydantic BaseModel** (not dataclass), `ProposalListResult(proposals: list[ProposalResult])`.

  Assign `proactive_hooks` from `hooks.py`: instantiate each `HookSpec` using the factory functions. Wire via `build_calendar_hooks(sync_engine: CalendarSyncEngine, cache_store: EventCacheStore, overlay_store: OverlayStore, *, owner_email: str, calendar_ids: list[str]) -> list[HookSpec]` factory in `hooks.py` (B6 fix: `sync_engine` replaces `client + cache_store` for the change-detection hook). Call it from `manifest.py`.

  — done when: `uv run mypy --strict src` passes; manifest built via factory with `OverlayTools` fakes shows 6 new overlay tools with bare names (no `calendar.` prefix — B9); `len(proactive_hooks) == 7`; each hook has `tier=1`; `OWNER_PRIVATE ⇒ tier==1` M6-a validator passes.

- [ ] Task 5: Off-hardware tests — files: `/Users/artemis-build/artemis/tests/test_calendar_overlay_hooks.py` — typed pytest using `FakeCalendarClient`, `FakeKeyProvider` (M2-b), fake `OverlayStore` (backed by a `tmp_path` SQLite via `sqlcipher_open` with a test key), `FakeModelPort` (M6-b pattern), and in-test fake `CacheStore`:

  **Overlay store**:
  - `hold_tentative` with `FakeCalendarClient` → creates a Google event with `status="tentative"` and `extendedProperties.private.artemis_overlay=<proposal_id>`; row saved to store with `google_event_id` set.
  - `approve_proposal` → `FakeCalendarClient.update_event` called with `{"status": "confirmed"}`; store row has `status="approved"`.
  - `reject_proposal` → `FakeCalendarClient.cancel_event(row.google_event_id, recurrence_scope="THIS_EVENT", send_updates="none")` called; row has `status="rejected"`.
  - `list_proposals` returns only `status="pending"` rows.
  - locked `key_provider` → `ScopeLockedError` on any store method (before any Google call).

  **Marker round-trip / no double-count**:
  - Create a hold via `hold_tentative`; feed the returned `google_event_id` through `FakeCalendarClient`'s event list WITH `extendedProperties.private.artemis_overlay` set; call CAL-a `sync()` (or a stub that inspects the marker); assert the event is flagged as `own_projection=True` and NOT added to the regular event cache as an external event.

  **Hook firing**:
  - `make_upcoming_reminder_check` with a fake cache containing an event 10 min from now → `check_ref()` returns `hit=True` with `starts_in_minutes` ≈ 10.
  - `make_change_detection_check` with a `FakeCalendarClient` whose `sync()` stub returns `changed_count=2` → `hit=True` with `changed_count=2`.
  - `make_conflict_alert_check` with two overlapping events in the fake cache → `hit=True` with `conflict_count=1`.
  - `make_free_gap_check` with no existing holds and a 2h free gap → `hit=True` AND a new pending `kind="hold"` proposal exists in the store; calling the check again immediately → `hit=False` (already-pending dedup).
  - `make_unanswered_invite_check` with 3 events where owner RSVP is `needsAction` → `hit=True`, `invite_count=3`.
  - `make_prep_nudge_check` with an event 12h from now → `hit=True`; payload contains `event_id` but NO raw title/description field.
  - `make_daily_briefing_check` with 3 events today → `hit=True`; payload contains `event_count=3`; payload does NOT contain any raw externally-authored string field.

  **Tier-1 queueing**:
  - Build a `ModuleManifest` with one of the calendar hooks; wrap it in a `ToolRegistry` + `Heartbeat(registry, FakeKeyProvider(owner_unlocked=False))`; call `tick()` → the hook's `check_ref` is NOT called, its name appears in `tick().tier1_skipped`.
  - With `FakeKeyProvider(owner_unlocked=True)` → the hook runs normally.

  **Intentions stub**:
  - `_intentions_projection_stub()` returns `None` and does not raise; no `HookSpec` in the manifest is named `"cal_intentions"` (stub is not wired).

  **`_quarantine_stub`**:
  - Calling `_quarantine_stub("external title with <script>")` returns `"[external content pending quarantine]"` and does not raise.

  **Overlay manifest factory (tool count + bare names)**:
  - Build the overlay specs via `make_calendar_overlay_manifest(overlay_tools)` with the `OverlayTools` instance wired to the fakes (the same `overlay_tools` fixture used above); assert `len(specs) == 6` and `all("." not in t.name for t in specs)` (B9 — bare names, no `calendar.` prefix). (Replaces the former non-runnable `tools=None` `python -c` AC.)

  **ADR-016 note:** the overlay-store tests above call the module-level functions (`hold_tentative`, `approve_proposal`, `reject_proposal` — sync `def`) directly, so they remain sync tests. If a test instead exercises an `OverlayTools` method (the `callable_ref`), it must `await` it under `pytest.mark.asyncio`. Hook `check_ref()` calls stay sync (Seam 5).

  — done when: `uv run pytest -q tests/test_calendar_overlay_hooks.py` passes AND `uv run mypy --strict src tests/test_calendar_overlay_hooks.py` passes.

- [ ] Task 6 (GATED — on-hardware): Real projection + approve/reject against Google + real change-detection — files: (no new repo files; uses Tasks 1–5 + real `GoogleCredentialsFactory` + real broker) — on the Mini, vault unlocked:
  (a) `hold_tentative("2026-06-15T10:00:00Z", "2026-06-15T11:00:00Z", "Test Hold")` → event appears in Google Calendar as tentative with the `artemis_overlay` private extended property.
  (b) `approve_proposal(<id>)` → event status changes to confirmed in Google Calendar.
  (c) Run CAL-a `sync()` → the tentative event is recognised as an own-projection (not re-ingested as external); after approve it is treated as a normal event.
  (d) `reject_proposal(<id>)` on a fresh hold → Google event is deleted.
  (e) `make_change_detection_check` fires a real `syncToken` poll → detects the changes above and returns `hit=True`.
  — done when: (a)–(e) verified and recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/calendar/overlay.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/calendar/hooks.py` |
| Create | `/Users/artemis-build/artemis/tests/test_calendar_overlay_hooks.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_calendar_overlay_hooks.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_calendar_overlay_hooks.py` | Test gate (overlay lifecycle, hooks, Tier-1 queueing) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/calendar/overlay.py`, `src/artemis/modules/calendar/hooks.py`, `src/artemis/modules/calendar/manifest.py`, `tests/test_calendar_overlay_hooks.py` |
| `git commit` | `"feat: CAL-c proposal/hold overlay + Google tentative projection + §D proactive hooks"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | GATED on-hardware only (Task 6) |
| `ARTEMIS_ENV_FILE` / `ARTEMIS_DATA_ROOT` / `ARTEMIS_SLOT` | Settings + scope_dir path resolution (M0-a) |

### Network
| Action | Purpose |
|--------|---------|
| HTTPS to `www.googleapis.com` (GATED, on-Mini only) | Real projection/approve/reject/sync (Task 6). No network in off-hardware tests. |

## Specialist Context

### Security
- **Overlay store is Tier-1 / owner-private**: opened only with the broker DEK via `sqlcipher_open`; `ScopeLockedError` propagates on locked access; `dek_for_scope` key hex lives only in a local variable inside `_connect()` (M8-a pattern — never instance attribute).
- **Projected holds are self-only → auto write-through**: consistent with CAL-shared decision 3 (no attendees → no gated path). `approve_proposal` checks `is_self_only` (CAL-b `gating.py`) at runtime; self-only → direct write-through via `client.update_event` (or a `CalendarWriteTools` method when `google_event_id` is None); attendee case → stages via `ActionStagingService.stage(...)` (GATE-a) and returns without executing — the pending action is approved separately through the Review screen (ADR-012 §3). M7-b `RecipeStore` is NOT used for this one-off instance path.
- **Projection marker `artemis_overlay` in `extendedProperties.private`**: Google `private` extended properties are visible only to the creating app — the hold marker is not exposed to other calendar viewers. Reject/approve must always clean the projected event (no orphan tentatives left on Google after rejection).
- **LLM injection surface in hooks**: `needs_llm=True` hooks (daily_briefing, prep_nudge) pass payloads through M6-b's batched LLM call. The `_quarantine_stub` ensures NO externally-authored event text reaches the LLM until CAL-d's `quarantine_event_text` is wired. Payload fields for these hooks are limited to event IDs and numeric fields only. Flag for CAL-d security review: confirm every hook payload that feeds the LLM is sanitised via `quarantine_event_text` once CAL-d lands.
- **`needs_llm=False` hooks** render via the M6-b `TemplateRegistry` (deterministic). Templates are registered in `hooks.py` and select only numeric/ID payload fields — no raw event text in notification bodies until CAL-d.
- **`ReauthRequiredError` graceful degradation**: every hook's `check_ref` that calls the `CalendarClient` wraps the call in `try/except ReauthRequiredError` → returns `HookResult.miss()` + logs; does NOT crash the tick or the `run_forever` loop.
- **All calendar hooks are Tier-1**: enforced structurally by the M6-a `OWNER_PRIVATE ⇒ tier==1` manifest validator; they are queued while the vault is locked and run only when the owner session is unlocked (ADR-006).

### Performance
- `make_change_detection_check` calls CAL-a `sync()` every 5 min (interval_seconds=300) — the incremental `syncToken` path touches Google only when the token indicates changes. Off no-change ticks it is a lightweight poll returning `HookResult.miss()` (zero hit-handling cost).
- `make_upcoming_reminder_check` and `make_conflict_alert_check` read only the in-process cache (no Google calls off-hardware or when the cache is warm).
- `approve_proposal` performs one `client.update_event` (or `create_event`) call — no extra Google round-trips.

### Accessibility
(none — no frontend; notification copy is a content concern handled by M6-b's template/LLM path)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/calendar/overlay.py` | TSDoc all exports; document the projection lifecycle (hold→tentative→approve→confirmed; reject→delete), the `ScopeLockedError` propagation contract, the `_quarantine_stub` TODO |
| Inline | `src/artemis/modules/calendar/hooks.py` | Docstring each hook factory; document Tier-1 + the `_quarantine_stub` boundary; document the intentions-projection stub |
| Inline | `src/artemis/modules/calendar/manifest.py` | Document the new tools + hooks entries; note the `build_calendar_hooks` composition point |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_calendar_overlay_hooks.py` → verify: exit 0.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] Run `uv run pytest -q tests/test_calendar_overlay_hooks.py` → verify: `hold_tentative` creates a tentative Google event with the `artemis_overlay` marker; `approve_proposal` promotes it to confirmed; `reject_proposal` deletes it; `list_proposals` returns only pending rows; a locked `key_provider` raises `ScopeLockedError`; marker reconciliation test passes (no double-count in sync); all 7 hook `check_ref`s return `HookResult` with correct `hit` values against fake cache data; free-gap hook emits a hold proposal and dedups on re-fire; Tier-1 queueing test passes (hook skipped while locked, runs when unlocked); `_quarantine_stub` returns the placeholder and no raw text appears in `needs_llm` payloads; intentions stub is a no-op; all pass.
- [ ] Run `uv run pytest -q tests/test_calendar_overlay_hooks.py -k manifest` → verify: the overlay-manifest-factory test (Task 5) passes — specs built via `make_calendar_overlay_manifest(overlay_tools)` with the wired `OverlayTools` fakes number 6 and all `ToolSpec.name`s are bare (no `calendar.` prefix — B9). (Replaces the former non-runnable `tools=None` `python -c` AC; B8 — built via factory, no `CALENDAR_MANIFEST` constant.)
- [ ] Run `uv run python -c "from artemis.modules.calendar.overlay import OverlayProjectionError, ProposalNotFoundError, OverlayTools; print('ok')"` → verify: prints `ok` (OverlayTools class exists for B7 bound-method pattern).
- [ ] Run `uv run python -c "from artemis.modules.calendar.hooks import build_calendar_hooks; from artemis.modules.calendar.manifest import make_calendar_manifest; hooks = None; print('hook factories importable')"` → verify: exits 0 (hook factory importable with `sync_engine` param instead of `client+cache_store` — B6 fix).
- [ ] (GATED, on Mini, vault unlocked) `hold_tentative` creates a real tentative event in Google Calendar with the `artemis_overlay` extended property; `approve_proposal` confirms it; `reject_proposal` on a fresh hold deletes the Google event; `sync()` recognises own-projections and does not double-count them; change-detection hook fires on a real syncToken delta → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
