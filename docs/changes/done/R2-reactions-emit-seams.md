---
spec: R2-reactions-emit-seams
status: ready
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R2 — Reactions emit seams (gmail post-detect Option-B + calendar scalar) + wire four producers

**Identity:** Wires the producer-side emit seams. Gmail emits `EMAIL_INGESTED` **post-extraction** (Fork 1b) with the **Fork-1 Option-B thin payload** (`message_id`, `source_ref`, + non-sensitive flags `has_commitment`/`has_event`/`has_gift_signal`) after running the R5d classifier + storing the structured extract; calendar emits scalar-only `EVENT_INGESTED`. Wires `bus.emit` into all four producers (finance, trips, gmail, calendar).
<!-- → why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (§ Amendment: Forks 1/1b + Email structured-extract layer; Decision 3). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- `GmailMemoryExtractor.extract` (`gmail/ingest.py:175`), driven per signal message by `GmailSync` (`sync.py:92,177`), is the post-extraction emit site for `EMAIL_INGESTED` — it already holds the laundered `Extract` (line 177) and runs once per signal message. This OVERRIDES the original "emit at `ingest_message`" plan (Fork 1b: emit post-extraction so flags exist). → impact: Stop (emitting at `ingest_message` predates the laundered extract → no flags to compute).
- Emit fires only when `extract.usable` (the existing gate at `ingest.py:183`) AND the R5d classifier returns a non-`None` `StructuredEmailExtract`. Skipping non-usable / injection-flagged / unclassifiable mail is intended (Fork 1b); the classifier already logs (does not swallow) transient failures. → impact: Stop (emitting on a non-usable extract fans potentially-tainted routing).
- The `EMAIL_INGESTED` payload carries ONLY scalars: `{message_id, source_ref}` + the three non-sensitive flags `has_commitment`/`has_event`/`has_gift_signal` — NEVER summary, body, subject, sender, claims, event fields, or model output. The structured content lives in the R5d owner-private store; reactions fetch it via `source_ref` (R6c). The event `dedup_key = f"email-ingested:{message_id}"`. → impact: Stop (any content field is a `DomainEvent` validator failure AND a Fork-1/OWASP-LLM01 wall violation on live untrusted email).
- `CalendarSyncEngine` (`calendar/cache.py:179`), not `EventCacheStore`, is the `EVENT_INGESTED` emit site: it owns `_full_sync`/`_incremental_sync` and the added-vs-updated decision. Emit fires once per upserted non-cancelled `CachedEvent`. Calendar carries NO detection layer — its fields are already structured/laundered upstream — so the payload is scalar-only `{event_id, calendar_id, start_dt, end_dt, externally_authored}`. → impact: Stop (emitting from `EventCacheStore.upsert` also fires on overlay-projection writes; calendar text fields are untrusted external content and must not be in the payload).
- New injected ctor params default to module-level no-ops / `None`, so off-composition behaviour is unchanged: `GmailMemoryExtractor(classifier=None, extract_store=None, emit=_noop_emit)`; `CalendarSyncEngine(emit=_noop_emit)`. The four producers are wired to `bus.emit` at their CONSTRUCTION sites (no app-root exists yet — R1 documented that); "wired" is verified by a composition test constructing each with a shared bus. → impact: Caution (when the app-root lands it must pass `bus.emit` to all four; R2 guarantees the seams accept it).
- `EMAIL_INGESTED` and `EVENT_INGESTED` already exist as `EventType` members (`emit.py:23,30`). `DomainEvent.depth` defaults to 0 (R1) — producers emit at depth 0, unset. → impact: Low.

Simplicity check: the gmail emit is gated behind both `extract.usable` AND a successful classify, so it only fires on mail that genuinely produced a structured extract — no speculative emits, and the untrusted body never enters the payload (it stays behind `source_ref` in the owner-private store).

## Prerequisites
- Specs that must be complete first: **R1** (`EventBus` + `DomainEvent.depth`) and **R5d** (`EmailClassifier` + `EmailExtractStore` + `StructuredEmailExtract`). Wave 2.
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/modules/gmail/ingest.py` | modify | `GmailMemoryExtractor` gains `classifier`/`extract_store`/`emit` params; classify+store+emit `EMAIL_INGESTED` (Option-B) after the usable gate. |
| `src/artemis/modules/calendar/cache.py` | modify | `CalendarSyncEngine` gains `emit`; emit scalar `EVENT_INGESTED` per upserted non-cancelled event. |
| `tests/test_reactions_emit_seams.py` | create | gmail Option-B payload (flags + no content), calendar scalar emit, four-producer reachability, no-op defaults. |

## Tasks
- [ ] Task 1: gmail `EMAIL_INGESTED` post-detect seam. Add `from artemis.reactions import DomainEvent, EventType` + a module-level `def _noop_emit(_e: DomainEvent) -> None: ...`. Add kw-only ctor params `classifier: EmailClassifier | None = None`, `extract_store: EmailExtractStore | None = None`, `emit: Callable[[DomainEvent], None] = _noop_emit` to `GmailMemoryExtractor`, stored on `self._classifier`/`self._extract_store`/`self._emit`. In `extract`, after `if not extract.usable: return False` and BEFORE the memory-enqueue block (so the reaction fires even if memory text is empty), if `self._classifier is not None`: `structured = await self._classifier.classify(extract)`; if `structured is not None`: `if self._extract_store is not None: self._extract_store.put(structured)`, then `self._emit(DomainEvent(event_type=EventType.EMAIL_INGESTED, source_module="gmail", payload={"message_id": message_id, "source_ref": f"gmail:{message_id}", "has_commitment": structured.has_commitment, "has_event": structured.has_event, "has_gift_signal": structured.has_gift_signal}, occurred_at=now_iso(), dedup_key=f"email-ingested:{message_id}"))`. Payload contains NO body/subject/sender/summary/claims/event-fields. **Ordering = store-then-emit** (the extract is `put` BEFORE the event is emitted, so a reaction fetching by `source_ref` always resolves). Failure semantics: a `put` failure → log + skip the emit (no orphaned event whose fetch would miss); a `put` that succeeds but `emit` that raises → log a warning, accept the orphan (R5d store TTL prunes it; a missed reaction is safe). The whole block is wrapped so any failure logs (not swallows) and does not abort the memory-enqueue path. — files: `src/artemis/modules/gmail/ingest.py` — done when: a usable, classifiable message emits exactly one `EMAIL_INGESTED` whose payload keys are exactly `{message_id, source_ref, has_commitment, has_event, has_gift_signal}` (scalars), the structured extract is `put` to the store, and the raw body/subject is absent from `repr(event)`; a non-usable extract or `classifier=None`/`classify→None` emits nothing; with no `emit`/`classifier` injected, `extract` returns its bool exactly as before.
- [ ] Task 2: calendar `EVENT_INGESTED` scalar seam. Add `from artemis.reactions import DomainEvent, EventType` + `from artemis.memory.schema import now_iso` + a module-level `_noop_emit`. Add kw-only `emit: Callable[[DomainEvent], None] = _noop_emit` to `CalendarSyncEngine.__init__` stored on `self._emit`. Add `def _emit_event_ingested(self, event: CachedEvent) -> None` emitting `DomainEvent(event_type=EventType.EVENT_INGESTED, source_module="calendar", payload={"event_id": event.event_id, "calendar_id": event.calendar_id, "start_dt": event.start_dt, "end_dt": event.end_dt, "externally_authored": event.externally_authored}, occurred_at=now_iso(), dedup_key=f"event-ingested:{event.event_id}:{event.calendar_id}")`. Call it immediately after each `self._store.upsert(cached)` in `_full_sync` and the non-cancelled branch of `_incremental_sync` (capture the `CachedEvent` as a local `cached`); do NOT emit in the cancelled/delete branch. Payload contains NO summary/description/location/attendees/raw_json. — files: `src/artemis/modules/calendar/cache.py` — done when: a sync upserting N non-cancelled events emits `EVENT_INGESTED` N times with payload keys exactly `{event_id, calendar_id, start_dt, end_dt, externally_authored}`; cancelled events emit nothing; with no `emit` injected, sync behaves exactly as before.
- [ ] Task 3: Tests `tests/test_reactions_emit_seams.py`. (a) **gmail Option-B** — drive `GmailMemoryExtractor.extract` with a fake reader (usable extract) + a fake `EmailClassifier` returning a `StructuredEmailExtract` with `has_commitment=True` + a fake `EmailExtractStore` + a capturing `emit`; assert one `EMAIL_INGESTED`, payload keys `== {"message_id","source_ref","has_commitment","has_event","has_gift_signal"}`, all scalar, the structured extract was `put`, and the fake raw body/summary text is ABSENT from `repr(event)`. (b) **gmail no-emit** — a non-usable extract, and a `classify→None`, each emit nothing. (c) **calendar** — a full sync over (confirmed×N, cancelled×1) with a capturing `emit`; `EVENT_INGESTED` fired N times, never for cancelled, payload values all scalar. (d) **four-producer reachability** — a real `EventBus`, subscribe a sink, build all four producers with `emit=bus.emit` and trigger one ingest each; the gmail leg MUST be constructed with a non-None fake `classifier` (returning a usable structured extract) + fake `extract_store` so the full Option-B path actually fires (otherwise the `classifier=None` guard silently emits nothing and the test would pass for the wrong reason); assert one event of each of `{TXN_RECORDED|BILL_RECORDED, TRIP_ASSEMBLED, EMAIL_INGESTED, EVENT_INGESTED}` reaches the sink. (e) **no-op default** — construct `GmailMemoryExtractor` (no classifier/emit) + `CalendarSyncEngine` (no emit), run extract/sync, assert no exception + baseline return values. — files: `tests/test_reactions_emit_seams.py` — done when: `uv run pytest -q tests/test_reactions_emit_seams.py` passes.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

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
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/gmail/ingest.py src/artemis/modules/calendar/cache.py tests/test_reactions_emit_seams.py` |
| `git commit` | "feat: R2 reactions emit seams (gmail Option-B post-detect + calendar scalar) + wire four producers" |

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
`cross_model_review: true` — these emit seams sit on LIVE untrusted ingest paths. Hard invariant: the `EMAIL_INGESTED` payload is `{message_id, source_ref}` + three booleans ONLY — never raw body/subject/sender/summary/claims/event-fields/model output (Fork-1 claim-check; untrusted content stays behind `source_ref` in the owner-private store). Reviewer must confirm: (1) the gmail payload keys are exactly the five scalars; (2) the structured extract goes to the owner-private store, never the payload; (3) emit is gated behind `extract.usable` + a successful classify; (4) the calendar payload carries no event text; (5) classify/store/emit failure logs and does not abort ingest.

### Performance
(none — `EventBus.emit` is sync enqueue; one classify+store+emit per signal email.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/gmail/ingest.py` | Comment on the emit point: post-detect, Option-B scalar payload, no content. |
| Inline | `src/artemis/modules/calendar/cache.py` | Comment on `_emit_event_ingested`: scalar-only payload. |
| ADR | docs/technical/adr/ADR-032-reactions-runtime-composition.md | Already amended (Forks 1/1b + email layer). No change. |

## Acceptance Criteria
- [ ] gmail `EMAIL_INGESTED` Option-B → verify: a usable+classifiable message emits one event; payload keys `== {message_id, source_ref, has_commitment, has_event, has_gift_signal}`; all scalar; structured extract `put` to the store; raw body/summary absent from `repr(event)`.
- [ ] gmail no-emit → verify: non-usable extract and `classify→None` emit nothing; no classifier/emit injected → `extract` returns its bool unchanged.
- [ ] calendar `EVENT_INGESTED` scalar → verify: full sync over (confirmed×N, cancelled×1) emits N times, never for cancelled; payload scalar-only, no text fields.
- [ ] Four-producer reachability → verify: `emit=bus.emit` on all four delivers one event of each expected `EventType` to a sink.
- [ ] No-op default preserved → verify: constructing without `emit`/`classifier` and running extract/sync raises nothing, returns baseline values.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
