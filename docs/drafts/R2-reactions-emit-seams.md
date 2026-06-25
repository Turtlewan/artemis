---
spec: R2-reactions-emit-seams
status: draft
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R2 — Reactions emit seams (gmail + calendar) + wire all four emitters

**Identity:** Adds the missing `EMAIL_INGESTED` (gmail ingest) and `EVENT_INGESTED` (calendar sync) producer-side emit seams with scalar-only `DomainEvent` payloads, and wires `bus.emit` (from R1's `compose_reactions` `EventBus`) into all four producers (finance, trips, gmail, calendar). Without the gmail seam the comms reactions (A4/A5/A7) can never fire.
<!-- → why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (Decision 3). -->

## Assumptions
- `GmailIngestor.ingest_message` (`src/artemis/modules/gmail/ingest.py`, line 131) is the single per-message ingest entry point and the correct emit site for `EMAIL_INGESTED` — it already holds `message_id` and is called once per signal message by `GmailSync` (`sync.py`). The new `emit` is an injected ctor param defaulting to a module-level no-op (mirroring finance `events._noop_emit`), so off-composition behaviour is unchanged. → impact: Stop (if ingest is driven from a different fan-out point the emit could double-fire or miss).
- `CalendarSyncEngine` (`src/artemis/modules/calendar/cache.py`, line 179), not `EventCacheStore`, is the emit site for `EVENT_INGESTED`: it owns `_full_sync`/`_incremental_sync` and decides added-vs-updated. Emit fires once per upserted (non-deleted) event inside both sync paths, keyed by `event_id:calendar_id` for dedup. `emit` is an injected ctor param defaulting to no-op. → impact: Stop (emitting from `EventCacheStore.upsert` instead would also fire on overlay-projection writes, which are not real ingests).
- The `EMAIL_INGESTED` payload carries ONLY scalars: `message_id` (str) plus the quarantined source ref `source_ref = f"gmail:{message_id}"` (the `Extract.source_url` convention from `GmailMemoryExtractor.extract`, ingest.py line 179) — NEVER `summary`, `claims`, raw body, subject, sender, or any model output. The event is emitted at ingest time on `message_id` alone; it does not require the quarantined `Extract` to be in scope. → impact: Stop (any non-scalar/text payload is both a `DomainEvent` validator failure and a security-wall violation on live untrusted email).
- The `EVENT_INGESTED` payload carries ONLY scalars: `event_id`, `calendar_id`, `start_dt`, `end_dt`, `externally_authored` (bool) — never `summary`, `description`, `location`, `attendees`, `organizer_email`, or `raw_json`. → impact: Stop (calendar text is untrusted external content; same wall as email).
- The four producers are wired to `bus.emit` at each producer's **construction site**, not inside `compose_reactions` — R1 fixed `compose_reactions` as a thin wiring root that returns `(bus, pre_tick_step)` and explicitly leaves producer-emit wiring to R2 (R1 Assumption 5). The construction sites are: `finance_manifest(emit=bus.emit)` (caller of `finance_manifest`), `TripAssembler(repo, entity_repo, emit=bus.emit)`, `GmailIngestor(..., emit=bus.emit)`, `CalendarSyncEngine(client, store, prefs, emit=bus.emit)`. This spec adds the two new ctor params and a wiring note; the actual app-root that owns all four call sites does not yet exist (R1 documented no daemon mount), so "wired" is verified by a composition test that constructs each producer with a shared bus and asserts emission reaches the bus. → impact: Caution (when the app-root lands, it must pass `bus.emit` to all four; this spec guarantees the seams accept it).
- `EVENT_INGESTED` and `EMAIL_INGESTED` already exist as `EventType` members (`src/artemis/reactions/emit.py` lines 23, 30) — no enum change is needed. → impact: Low (if absent, add them; verified present at authoring).

Simplicity check: considered emitting `EMAIL_INGESTED` from `GmailMemoryExtractor.extract` (where the `Extract` is in scope) instead of `GmailIngestor.ingest_message` — rejected: extraction is best-effort and skipped for non-usable/injection-flagged mail, so comms reactions would silently never fire on exactly the emails that matter; ingest is the reliable once-per-message seam and needs only `message_id` (a scalar) to emit safely.

## Prerequisites
- Specs that must be complete first: **R1** (`compose_reactions` + `EventBus` must exist — this spec wires `bus.emit` and the composition test imports `EventBus`).
- Environment setup required: none (uses existing `uv` toolchain).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/modules/gmail/ingest.py` | modify | Add `emit` ctor param + `_noop_emit` to `GmailIngestor`; emit `EMAIL_INGESTED` (scalar-only) in `ingest_message`. |
| `src/artemis/modules/calendar/cache.py` | modify | Add `emit` ctor param + `_noop_emit` to `CalendarSyncEngine`; emit `EVENT_INGESTED` (scalar-only) per upserted event in `_full_sync`/`_incremental_sync`. |
| `tests/test_reactions_emit_seams.py` | create | gmail/calendar scalar-only emit tests + four-producer reachability + no-op default tests. |

## Tasks
- [ ] Task 1: Add the `EMAIL_INGESTED` emit seam to `GmailIngestor`. Add `from collections.abc import Callable` (already imported) and `from artemis.reactions import DomainEvent, EventType`; define a module-level `def _noop_emit(_event: DomainEvent) -> None: ...`. Add `emit: Callable[[DomainEvent], None] = _noop_emit` as a keyword-only ctor param stored on `self._emit`. In `ingest_message`, after `self._cache.mark_body_ingested(message_id)` and before `return count`, emit a `DomainEvent(event_type=EventType.EMAIL_INGESTED, source_module="gmail", payload={"message_id": message_id, "source_ref": f"gmail:{message_id}"}, occurred_at=<iso now>, dedup_key=f"email-ingested:{message_id}")`. Use `artemis.memory.schema.now_iso` for the timestamp (matches finance/trips). The payload must contain NO body/subject/sender/summary/claims. — files: `src/artemis/modules/gmail/ingest.py` — done when: ingesting a message calls `emit` exactly once with an `EMAIL_INGESTED` event whose payload keys are exactly `{"message_id","source_ref"}` and all values are `str`; with no `emit` injected, ingest still returns its count and raises nothing.
- [ ] Task 2: Add the `EVENT_INGESTED` emit seam to `CalendarSyncEngine`. Add `from collections.abc import Callable` and `from artemis.reactions import DomainEvent, EventType` plus `from artemis.memory.schema import now_iso`; define a module-level `def _noop_emit(_event: DomainEvent) -> None: ...`. Add `emit: Callable[[DomainEvent], None] = _noop_emit` as a keyword-only param to `CalendarSyncEngine.__init__` stored on `self._emit`. Add a private helper `def _emit_event_ingested(self, event: CachedEvent) -> None` that emits `DomainEvent(event_type=EventType.EVENT_INGESTED, source_module="calendar", payload={"event_id": event.event_id, "calendar_id": event.calendar_id, "start_dt": event.start_dt, "end_dt": event.end_dt, "externally_authored": event.externally_authored}, occurred_at=now_iso(), dedup_key=f"event-ingested:{event.event_id}:{event.calendar_id}")`. Call it immediately after each `self._store.upsert(cached)` in `_full_sync` and in the non-cancelled branch of `_incremental_sync` (capture the `CachedEvent` in a local `cached` so the upsert and emit share one object; do NOT emit in the `cancelled`/delete branch). Payload must contain NO summary/description/location/attendees/raw_json. — files: `src/artemis/modules/calendar/cache.py` — done when: a sync that upserts N non-cancelled events calls `emit` N times with `EVENT_INGESTED` events whose payload keys are exactly `{"event_id","calendar_id","start_dt","end_dt","externally_authored"}`; cancelled events emit nothing; with no `emit` injected, sync behaves exactly as before.
- [ ] Task 3: Write `tests/test_reactions_emit_seams.py`. Cover: (a) **gmail scalar-only** — drive `GmailIngestor.ingest_message` with a fake pipeline/cache and a capturing `emit`; assert one `EMAIL_INGESTED` event, payload keys `== {"message_id","source_ref"}`, every payload value `isinstance(str)`, and the raw body/subject string used in the fake message does NOT appear in `repr(event)` (no-raw-body invariant). (b) **calendar** — drive a `CalendarSyncEngine` full sync with a fake client returning ≥1 confirmed + 1 cancelled event and a capturing `emit`; assert `EVENT_INGESTED` fired once per confirmed event, never for the cancelled one, and payload values are all scalars (`str|int|float|bool`). (c) **four-producer reachability** — construct a real `EventBus` (from `artemis.reactions`), subscribe a sink, build all four producers passing `emit=bus.emit` (finance via `finance_manifest(emit=bus.emit)`, trips via `TripAssembler(..., emit=bus.emit)`, gmail via `GmailIngestor(..., emit=bus.emit)`, calendar via `CalendarSyncEngine(..., emit=bus.emit)`), trigger one ingest on each, and assert the sink received one event of each of the four types `{TXN_RECORDED|BILL_RECORDED, TRIP_ASSEMBLED, EMAIL_INGESTED, EVENT_INGESTED}` (use whichever finance event the existing finance test path already exercises). (d) **no-op default** — construct `GmailIngestor` and `CalendarSyncEngine` with NO `emit`, run an ingest/sync, assert no exception and the same return values as a baseline. — files: `tests/test_reactions_emit_seams.py` — done when: `uv run pytest -q tests/test_reactions_emit_seams.py` passes.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `tests/test_reactions_emit_seams.py` |
| Modify | `src/artemis/modules/gmail/ingest.py`, `src/artemis/modules/calendar/cache.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format check. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/gmail/ingest.py src/artemis/modules/calendar/cache.py tests/test_reactions_emit_seams.py` |
| `git commit` | "feat: R2 reactions emit seams (gmail/calendar) + wire all four emitters" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installs. |

## Specialist Context
### Security
`cross_model_review: true` — these two new emit seams sit on LIVE untrusted ingest paths (external email bodies, external-authored calendar events). The hard invariant: emitted `DomainEvent` payloads are **scalar ids/timestamps only** — never raw body, subject, sender, summary, claims, description, location, attendees, or `raw_json`, and never model output. This is both a `DomainEvent` validator constraint (`emit.py` rejects non-scalars) AND a tested invariant in Task 3 (the no-raw-body assertion). Reviewer must confirm: (1) `EMAIL_INGESTED` payload is exactly `{message_id, source_ref}`, both `str`; (2) `EVENT_INGESTED` payload contains no event text fields; (3) emit fires at ingest time and does not pull the quarantined `Extract` summary/claims into the payload.

### Performance
(none — `EventBus.emit` is sync enqueue per ADR-032 Decision 2; one emit per ingested item is negligible.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/gmail/ingest.py` | One-line docstring/comment on the emit point noting scalar-only / no-raw-body. |
| Inline | `src/artemis/modules/calendar/cache.py` | One-line docstring/comment on `_emit_event_ingested` noting scalar-only payload. |
| ADR | docs/technical/adr/ADR-032-reactions-runtime-composition.md | Already written (this spec implements Decision 3). No change. |

## Acceptance Criteria
- [ ] gmail `EMAIL_INGESTED` seam → verify: `ingest_message` on a fake message emits exactly one `EMAIL_INGESTED` event; payload keys `== {"message_id","source_ref"}`; all values are `str`; the fake body/subject text is absent from `repr(event)`.
- [ ] calendar `EVENT_INGESTED` seam → verify: a full sync over (confirmed×N, cancelled×1) emits `EVENT_INGESTED` exactly N times, never for the cancelled event; every payload value is a scalar (`str|int|float|bool`); no text fields present.
- [ ] Four-producer reachability → verify: with a real `EventBus` and `emit=bus.emit` on finance, trips, gmail, calendar, a single trigger on each delivers one event of each of the four expected `EventType`s to a subscribed sink.
- [ ] No-op default preserved → verify: constructing `GmailIngestor` and `CalendarSyncEngine` without `emit` and running ingest/sync raises nothing and returns the same counts as baseline.
- [ ] `uv run mypy` → verify: no new errors.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: clean.
- [ ] `uv run pytest -q` → verify: full suite green.

## Progress
_(Coding mode writes here — do not edit manually)_
