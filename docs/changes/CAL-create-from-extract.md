---
spec: cal-create-from-extract
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- SPEC-LINT (2026-06-23): KEPT ready — the held-event creation (I-2 / C5=B: held tentative, NOT written
     to Google until approved) is sound and self-contained. ONE open FLAG (non-blocking): the drafter's
     coordination note assigns CAL the `held-event-created` event string to append to RXN-emit, but this spec
     never emits it AND no Wave-R recipe subscribes to it. Safe to build as-is (no consumer depends on the
     emit). OWNER: either drop `held-event-created` from the coordination contract, or — if a future reaction
     should chain off held-event creation — add EventType.HELD_EVENT_CREATED to RXN-emit + a bus.emit(...)
     here. Also FLAG: Task 3 marks the held row APPROVED while the attendee-gated Google write is still a
     pending GATE action (a "half-approved" state) — intentional + documented; confirm the semantics. -->

<!-- Wave R · NEW · I-2=B / C5=B. The ONE Calendar entry point taking a quarantined extract → a HELD
     TENTATIVE event (NOT written to Google until owner-approved). Home for all email→event reactions
     (A5/A7 playbooks). Approve → external Google write via the CAL-b write surface + GATE staging.
     cross_model_review: true (untrusted extract → calendar; external write on approve). -->

# Spec: CAL-create-from-extract — `calendar.create_from_extract` → held tentative event (approve → Google via GATE)

**Identity:** A new Calendar seam `calendar.create_from_extract(extract, *, event_type)` that turns a quarantined DR-a `Extract` into a **held tentative event** stored in Artemis (NOT written to Google), the single home for email→event reactions (A5 flight / A7 meeting playbooks); the owner approves a held tentative → it stages an external `calendar.create_event` write through GATE (`ActionStagingService`) → Google.
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (I-2=B email→held-tentative; C5=B hold-in-Artemis-until-approved) · docs/technical/adr/ADR-021-cross-module-reactions.md (email→calendar reaction home) · contracts.md Seam 3 (GATE) · Seam 4 (CalendarClient write) · Seam 7 (quarantine).

## Assumptions

- **CAL-b** complete: `CalendarWriteTools` (`create_event(CreateEventArgs) -> WriteResult|StagedResult`), `CreateEventArgs(summary, start_datetime, end_datetime, description=None, location=None, attendee_emails=[], calendar_id=None, recurrence=[], reminders=[])`, `WriteResult(event_id, summary, status, tool_name)`, the STRICT classifier (any attendee≠owner → GATED), the `create_event_execute` twin, and the `ActionStagingService` integration are importable from `artemis.modules.calendar`. → impact: Stop (the APPROVE path reuses CAL-b's gated `create_event` → `ActionStagingService.stage` → `create_event_execute` twin; this spec does NOT reinvent the Google write).
- **GATE-a** complete: `ActionStagingService.stage(module, tool, args, summary, *, ttl) -> PendingAction` (sync, Seam 3), `approve(id)` (async). The held-tentative APPROVE stages a `calendar.create_event` action exactly as CAL-b's gated path does — so a held event with attendees naturally routes through the same GATE the owner already uses. → impact: Stop.
- **DR-a** complete: `Extract` (`summary`, `claims`, `flagged_injection`, `parse_failed`, provenance) — the input is ALREADY quarantined upstream (the email→Extract parse rides the Gmail signal path / a Wave-R comms recipe). `create_from_extract` consumes the `Extract` + a small structured `EventExtract` (the calendar-relevant fields parsed from the Extract by the upstream step). → impact: Stop (this spec defines `EventExtract` as its input contract and tests with hand-built ones; raw mail never reaches here — Seam 7).
- **A held tentative event is NOT a Google event** (C5=B): it lives in an owned `held_event` SQLCipher table in the Calendar module's owner-private store. It is distinct from a confirmed cached event (it has no `event_id` until approved). The owner sees it in the Calendar detail overlay as "held tentative" (Wave U); approving it writes to Google and the held row is marked `approved` (carrying the resulting `event_id`). → impact: Stop (do NOT write to Google on create; the hold is the whole point).
- **Internal/reversible vs external (I-10):** *creating* a held tentative is internal/reversible → AUTO with an undoable notice (no GATE). *Approving* it (the Google write) is an external effect → GATE (`ActionStagingService`). This matches the owner's locked posture (internal auto, external holds). → impact: Stop.
- Off-hardware: `FakeCalendarClient` + a `FakeActionStagingService` spy + the held-event store over plain-sqlite fallback. No real Google. → impact: Low.

Simplicity check: considered writing the tentative straight to Google as `status="tentative"` — rejected; C5=B is explicit that the hold stays in Artemis until approved (a Google tentative is still an external write the owner didn't approve). Considered a new staging subsystem for held events — rejected; held events are an owned table + the existing GATE for the approve write. The minimum is: a `held_event` table + `create_from_extract` (auto, internal) + `approve_held_event` (stages via the existing CAL-b/GATE path).

## Prerequisites

- Specs complete: **CAL-a** (CalendarClient/prefs/store), **CAL-b** (write surface + classifier + `ActionStagingService` integration + `create_event_execute` twin), **GATE-a** (`ActionStagingService`), **DR-a** (`Extract`), **M2-b/c** (owned store).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/create_from_extract.py` | create | `EventExtract`, `HeldTentativeEvent`, `held_event` DDL + `HeldEventStore`, `create_from_extract(...)`, `approve_held_event(...)`, `list_held_events(...)`, `discard_held_event(...)` |
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` | modify | add `calendar.create_from_extract`, `calendar.approve_held_event`, `calendar.list_held_events`, `calendar.discard_held_event` ToolSpecs (additive) |
| `/Users/artemis-build/artemis/src/artemis/modules/calendar/__init__.py` | modify | re-export the new symbols |
| `/Users/artemis-build/artemis/tests/test_calendar_create_from_extract.py` | create | held-create (no Google write); approve → stages create_event via GATE; attendee → GATED; list/discard; idempotency on raw_ref |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: `EventExtract` + held-event store** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/create_from_extract.py` —

  ```python
  class EventExtract(BaseModel):                  # the calendar-relevant fields parsed from a DR-a Extract upstream
      model_config = ConfigDict(frozen=True)
      summary: str                                # sanitised event title (from Extract — never raw subject)
      start_datetime: str                         # ISO-8601
      end_datetime: str
      location: str | None = None
      description: str | None = None              # from Extract.summary (already sanitised)
      attendee_emails: tuple[str, ...] = ()       # parsed invitees (drive GATE on approve)
      raw_ref: str                                # source_message_id:line_index — idempotency key

  class HeldEventStatus(StrEnum):
      HELD = "held"; APPROVED = "approved"; DISCARDED = "discarded"

  @dataclass(frozen=True)
  class HeldTentativeEvent:
      id: str; event_type: str; summary: str
      start_datetime: str; end_datetime: str
      location: str | None; description: str | None
      attendee_emails: tuple[str, ...]
      status: HeldEventStatus
      raw_ref: str
      google_event_id: str | None                 # populated after approve
      pending_action_id: str | None               # the GATE PendingAction id after approve (if gated)
  ```

  `held_event` DDL via `create_held_event_schema(conn)` (idempotent, in the Calendar owner-private store): `id TEXT PRIMARY KEY, event_type TEXT NOT NULL, summary TEXT NOT NULL, start_datetime TEXT NOT NULL, end_datetime TEXT NOT NULL, location TEXT, description TEXT, attendee_emails TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'held' CHECK(status IN ('held','approved','discarded')), raw_ref TEXT NOT NULL, google_event_id TEXT, pending_action_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL`. **`UNIQUE idx_held_raw_ref` on `(raw_ref)`** (idempotency — re-processing the same email event never creates a duplicate hold). Index: `idx_held_status` on `(status)`.

  `class HeldEventStore` (constructed over the Calendar module's owned connection, M2-stub on dev): `create_held(extract, event_type) -> str` (ON CONFLICT(raw_ref) DO NOTHING → return existing id), `get_held(id)`, `list_held(*, status="held")`, `set_approved(id, *, google_event_id, pending_action_id)`, `set_discarded(id)`.

  — done when: `uv run mypy --strict src` passes; `create_held_event_schema` creates the table + `raw_ref` UNIQUE; `create_held` twice with the same `raw_ref` yields one row; `list_held(status="held")` returns held-only.

- [ ] **Task 2: `create_from_extract` (auto, internal — NO Google write)** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/create_from_extract.py` —

  `async def create_from_extract(extract: EventExtract, *, event_type: str, store: HeldEventStore) -> HeldTentativeEvent` (ADR-016: `callable_ref` is async; the store call stays sync inside):
  1. Create a HELD row: `held_id = store.create_held(extract, event_type)` (idempotent on `raw_ref`).
  2. Return `store.get_held(held_id)` (status `HELD`, `google_event_id=None`).
  - **NO Google write here** (C5=B). This is internal/reversible → AUTO with an undoable notice (the brain surfaces "held a tentative event — approve in Calendar"; discard is the undo). No GATE.

  **Security invariant (inline):** `# C5=B: create_from_extract NEVER writes to Google. The held tentative lives in the owned held_event table until the owner approves. The external Google write happens ONLY in approve_held_event, via the CAL-b gated create_event → GATE.`

  — done when: `uv run mypy --strict src` passes; `await create_from_extract(extract, event_type="flight", store=store)` returns a `HeldTentativeEvent(status=HELD, google_event_id=None)`; no `FakeCalendarClient.create_event` call occurs (assert call count 0); re-calling with the same `raw_ref` returns the same held id (no duplicate).

- [ ] **Task 3: `approve_held_event` (external write → GATE) + list/discard** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/create_from_extract.py` —

  `async def approve_held_event(held_id: str, *, store: HeldEventStore, write_tools: CalendarWriteTools) -> HeldTentativeEvent` (ADR-016 async):
  1. Load the held event; if not `HELD` → return it unchanged (idempotent; already approved/discarded).
  2. Build `CreateEventArgs(summary=h.summary, start_datetime=h.start_datetime, end_datetime=h.end_datetime, description=h.description, location=h.location, attendee_emails=list(h.attendee_emails))`.
  3. `result = await write_tools.create_event(args)` — **this reuses CAL-b's gated `create_event`** (Seam 4): the CAL-b classifier routes it — self-only (no attendees) → AUTO write-through (returns `WriteResult`, `google_event_id` set immediately); with attendees → GATED (returns `StagedResult`, a `PendingAction` staged via `ActionStagingService`, no Google write yet — the owner approves the GATE action separately).
  4. If `WriteResult` (AUTO): `store.set_approved(held_id, google_event_id=result.event_id, pending_action_id=None)`.
     If `StagedResult` (GATED): `store.set_approved(held_id, google_event_id=None, pending_action_id=result.pending_action_id)` — the held event is "approved by the owner to be created", but the actual Google write is now a PENDING GATE action (which the owner approves on the Review screen → `create_event_execute` twin writes to Google). Mark the held row status `APPROVED` either way (the owner has cleared the hold; the GATE handles the attendee-write approval as its own second gate).
  5. Return the updated `HeldTentativeEvent`.

  `async def list_held_events(*, store, status="held") -> list[HeldTentativeEvent]` (read tool). `async def discard_held_event(held_id, *, store) -> HeldTentativeEvent` (the undo for a held tentative — `set_discarded`; no Google involvement).

  **Invariant (inline):** `# The external Google write goes through CAL-b's create_event → its classifier → GATE for any attendee event. approve_held_event NEVER calls the Google client directly; it always goes through write_tools.create_event (Seam 4) so the attendee-gating wall holds.`

  — done when: `uv run mypy --strict src` passes; approving a self-only held event → `write_tools.create_event` returns a `WriteResult`, held row becomes `APPROVED` with `google_event_id` set; approving a held event WITH attendees → `create_event` returns a `StagedResult`, `FakeActionStagingService.staged` has one `calendar.create_event` entry, held row `APPROVED` with `pending_action_id` set and `google_event_id=None`; approving an already-approved held event is a no-op; `discard_held_event` sets `DISCARDED` without any client/staging call.

- [ ] **Task 4: Manifest tools** — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py`, `/Users/artemis-build/artemis/src/artemis/modules/calendar/__init__.py` (modify, additive) —

  Add 4 ToolSpecs (bare names per Seam 2; fq ids shown): `create_from_extract` (`calendar.create_from_extract`, WRITE, auto — internal hold), `approve_held_event` (`calendar.approve_held_event`, WRITE — routes external via GATE), `list_held_events` (`calendar.list_held_events`, READ), `discard_held_event` (`calendar.discard_held_event`, WRITE, auto). Wire the `HeldEventStore` + `write_tools` via the composition root (a `partial` over the async callables, mirroring CAL-b's wiring). Re-export new symbols.

  — done when: `uv run mypy --strict src` passes; the 4 tools appear in the Calendar manifest with correct bare names + risks; all callables are coroutine functions; no double-prefix in fq ids.

- [ ] **Task 5 (GATED — on-hardware):** On the Mini (Calendar vault + Google creds): `calendar.create_from_extract(<flight EventExtract>, event_type="flight")` creates a held row, NO Google event yet; `calendar.approve_held_event(id)` for a self-only event writes a real Google event (held → APPROVED, `google_event_id` set); for an attendee event stages a `PendingAction` (held → APPROVED with `pending_action_id`, Google write only after the owner approves the GATE action). — done when: recorded in handoff.

- [ ] **Task 6: Tests** — files: `/Users/artemis-build/artemis/tests/test_calendar_create_from_extract.py` — typed pytest; `FakeCalendarClient`, `FakeActionStagingService` (CAL-b spy), `FakeKeyProvider(owner_unlocked=True)`, `HeldEventStore` over plain-sqlite fallback, a real `CalendarWriteTools` wired to the fakes (CAL-b classifier exercised). Async tests `await` the callables.

  - **Held-create, no Google write:** `await create_from_extract(EventExtract(summary="SQ322 SIN→LHR", start_datetime=..., end_datetime=..., attendee_emails=(), raw_ref="m1:0"), event_type="flight", store=store)` → `status==HELD`, `google_event_id is None`; `FakeCalendarClient.create_event` call count == 0; held row present.
  - **Idempotency:** re-create with `raw_ref="m1:0"` → same held id, one row.
  - **Approve self-only → AUTO Google write:** `await approve_held_event(id, store=store, write_tools=wt)` for a no-attendee held event → `write_tools.create_event` AUTO path called Google client once; held row `APPROVED`, `google_event_id` set, `pending_action_id is None`; `FakeActionStagingService.staged` empty.
  - **Approve with attendees → GATED:** a held event with `attendee_emails=("other@x.com",)` → approve → `write_tools.create_event` GATED path; `FakeActionStagingService.staged` has one `calendar.create_event` entry; held row `APPROVED` with `pending_action_id` set, `google_event_id is None`; `FakeCalendarClient.create_event` NOT called (gated never executes).
  - **Approve idempotency:** approving an already-`APPROVED` held event is a no-op (no second create/stage).
  - **List + discard:** `list_held_events(status="held")` returns held-only; `discard_held_event(id)` → `DISCARDED`, no client/staging call.
  - **No raw text leak:** the held row stores only the sanitised `EventExtract.summary` (assert the store never receives a raw email body field — the `EventExtract` has no such field).

  — done when: `uv run pytest -q tests/test_calendar_create_from_extract.py` passes AND `uv run mypy --strict src tests/test_calendar_create_from_extract.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/calendar/create_from_extract.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/calendar/__init__.py` |
| Create | `/Users/artemis-build/artemis/tests/test_calendar_create_from_extract.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_calendar_create_from_extract.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_calendar_create_from_extract.py` | Test gate (fakes only) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/calendar/create_from_extract.py`, `src/artemis/modules/calendar/manifest.py`, `src/artemis/modules/calendar/__init__.py`, `tests/test_calendar_create_from_extract.py` |
| `git commit` | `"feat: calendar.create_from_extract — held tentative event (approve → Google via GATE)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + Calendar store path resolution |

### Network
| Action | Purpose |
|--------|---------|
| HTTPS to `www.googleapis.com` (GATED, on-Mini only, on approve) | Real event creation on approve |
| (none off-hardware) | Fakes; no network |

## Specialist Context

### Security

- **C5=B hold invariant:** `create_from_extract` NEVER writes to Google — the held tentative lives in the owned `held_event` table until the owner approves. The external write happens ONLY in `approve_held_event`, ALWAYS through CAL-b's `create_event` so the attendee-gating classifier + GATE wall holds (an attendee event → staged `PendingAction`, never a silent external write).
- **Quarantine boundary (Seam 7):** the input is an `EventExtract` derived from a DR-a `Extract` upstream — raw email subject/body NEVER reaches this layer (the `EventExtract` has no raw-text field; only the sanitised `summary`/`description`). The held row stores only sanitised fields.
- **Internal vs external posture (I-10):** creating a hold is internal/reversible (AUTO + undoable via discard); approving is external (GATE). This matches the owner's locked autonomy boundary exactly.
- Owned `held_event` table is owner-private SQLCipher (M2 wall; `ScopeLockedError` propagates). [apex-security (cross_model_review): confirm `approve_held_event` cannot bypass the CAL-b classifier (it must call `write_tools.create_event`, never the raw client); confirm no raw email text in the held row; confirm the GATE path is reused, not a parallel write.]

### Performance

- `create_from_extract` is one SQLCipher insert. `approve_held_event` is one `create_event` (AUTO: one Google write; GATED: one local stage insert, no network). Negligible at personal scale.

### Accessibility

(none — the held-tentative surface in the Calendar overlay is Wave U)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/calendar/create_from_extract.py` | Document the C5=B hold invariant (no Google write on create), the approve→GATE path (reuses CAL-b create_event), the EventExtract sanitised-input contract, and the held/approved/discarded lifecycle |
| Data model | `docs/technical/architecture/data-model.md` | Add the `held_event` table (Calendar owner-private scope) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_calendar_create_from_extract.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_calendar_create_from_extract.py` → verify: held-create writes no Google event; idempotent on raw_ref; approve self-only → AUTO Google write + APPROVED; approve with attendees → GATED stage (no Google write) + APPROVED with pending_action_id; approve idempotency; list/discard; no raw-text field in the held row.
- [ ] `uv run python -c "from artemis.modules.calendar.create_from_extract import create_from_extract, approve_held_event, EventExtract, HeldTentativeEvent; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) create_from_extract holds (no Google event); approve self-only writes Google; approve attendee stages a PendingAction → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
