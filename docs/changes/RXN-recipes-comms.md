---
spec: rxn-recipes-comms
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave R · per-cluster reaction recipes (Comms/email). Consumes the reaction infra (RXN-emit /
     RXN-rulestore / RXN-dispatcher) + capabilities (CAL-create-from-extract, TRIP-entity, MAPS-connector)
     + CaptureService (M8-d-c2). Defines ReactionRules + reaction callables for the A-cluster email
     reactions; builds NONE of the infra/capabilities it binds to. -->

# Spec: RXN-recipes-comms — Comms/email reaction recipes (A4 commitment→task · A5/A7 email→held-event · gift-signal + clip)

**Identity:** The Comms-cluster reaction recipes: registers `ReactionRule`s that bind email domain events to reaction callables — A4 (commitment → inert task suggestion via `CaptureService`), A5/A7 (flight/meeting email → held-tentative calendar event via `calendar.create_from_extract`, A5 assembling a `Trip`), and the gift-signal memory category + email-to-self clip channel. All judgment reactions are Tier-B (suggest→graduate); nothing here auto-writes an external system.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (Decision 1 three-tier · Decision 2 Tier-A gate · A-cluster) · docs/findings/cluster-decisions/DECISIONS-LOG.md (I-1 email→task inert · I-2 email→calendar held · I-11 gift-signal/clip · I-12 selective migrate).

## Assumptions

- **RXN-emit** complete: frozen `DomainEvent{event_type: EventType, source_module: str, entity_refs: tuple[EntityRef, ...], payload: dict[str, str|int|float|bool], occurred_at, dedup_key}` (payload = ids + scalars only, validated, never raw text — Seam 5/7). The Gmail spoke emits **`EventType.EMAIL_INGESTED`** (already registered) carrying the signal-email `message_id` + `extract_id` + sender entity ref + **payload-flag discriminator scalars** `commitment_detected: bool`, `event_kind: str` (`""`/`"flight"`/`"meeting"`), `gift_signal: bool` — these are computed by the ingest/quarantine pre-flight, NOT raw mail. **There are NO new `flight-email-detected`/`meeting-email-detected`/`commitment-detected`/`gift-signal-detected` event types** — they are scalar payload flags on the one `EMAIL_INGESTED` event (the canonical rulestore A4 already binds `reaction:email_to_task` to `EMAIL_INGESTED`); each reaction callable guards on its flag. → impact: Stop (this spec binds all email reactions to `EMAIL_INGESTED`; the flag scalars + emit point are RXN-emit/Gmail's contract — referenced, not built).
- **RXN-rulestore** complete: the canonical `ReactionRule` is a frozen dataclass `{name: str, event_type: EventType, tier: ReactionTier, external_effect: bool, reaction_ref: str (fq tool/recipe id), dedup_key_fields: tuple[str, ...], stateful: bool = False}`; Tier-B reactions register as M7 recipes (CANDIDATE→PENDING→ENABLED) whose `task_class_key` starts `"reaction:"` and surface from the RecipeStore. → impact: Stop (A4/A5/A7/gift are Tier-B; their `reaction_ref` is a `str` fq recipe id like `reaction:email_to_task`; idempotency is `dedup_key_fields`, NEVER an `idempotency_key_fn`; the rule carries NO `Callable`).
- **RXN-dispatcher** complete: subscribes to emitted events, matches `ReactionRule`s, dispatches via `await get_tool(rule.reaction_ref).callable_ref(args)` (async, ADR-016), composes the stable key from `rule.dedup_key_fields` over the payload + `event.dedup_key`, routes `external_effect=True` reactions through `ActionStagingService` (GATE). Internal/reversible reactions act with an undoable notice. → impact: Stop (the dispatcher resolves the fq-id'd callables this spec registers; the GATE/idempotency machinery is the dispatcher's, reused).
- **CAL-create-from-extract** complete: `calendar.create_from_extract(extract: Extract, *, event_type: str) -> HeldTentativeEvent` — builds a HELD tentative event (C5=B: NOT written to Google until owner-approved). The held-tentative store + the approve→Google (GATE) path live there. The valid `event_type` values are `"flight"`/`"meeting"` — there is NO `"airport_buffer"` value (the airport-leave block is owned by RXN-recipes-planning's `TRIP_ASSEMBLED` reaction, not created here — no double-home). → impact: Stop (A5/A7 call this for the held flight/meeting event; they never write Google directly and never create the airport block).
- **TRIP-entity** complete: `TripAssembler.assemble(self, extract: TripExtract) -> str` — stateful/windowed multi-email itinerary assembly (Decision 5: idempotent; the stable key is computed INSIDE `assemble` from destination+date-window — there is NO `trip_key=` kwarg), M4-homed beside Place; co-travel links PERSON entities; `assemble` returns the `trip_id` (a `str`) and emits `EventType.TRIP_ASSEMBLED` (which triggers the RXN-recipes-planning airport-leave block — A5 here does NOT build that block). The assembler's INPUT is a `TripExtract`, NOT a DR-a `Extract`: A5 builds a `TripExtract` from the quarantined `Extract` (the `raw_ref` is `message_id:line_index`) before calling `assemble`. → impact: Stop (A5 maps the Extract→TripExtract, calls `assemble(trip_extract)`, then creates the held flight event; the airport block is planning's).
- **MAPS-connector** complete (transitively, via RXN-recipes-planning): A5 here does NOT call Maps — the airport-leave block (which uses `MapsConnector.travel_time`/`FixedBufferFallback`) is owned by RXN-recipes-planning's `TRIP_ASSEMBLED` reaction, triggered by the assembler's emit. → impact: Low (no Maps dependency in comms.py; the on-hardware end-to-end Maps buffer surfaces via the planning reaction).
- **CaptureService** (M8-d-c2) complete: `suggest_from_text(source, text, *, untrusted) -> str | None` creates an INERT `suggestions` row; `accept_with_graduation` is the owner-accept path; email paths route through DR-a `QuarantinedReader` first. → impact: Stop (A4 reuses `CaptureService` verbatim — it does NOT define a new suggestion path; I-1: inert, owner accepts).
- **M4-b module fact-push** (ADR-021 dependency #1) complete: `MemoryStore.add_fact` callable by a module + the gift-signal extraction category. The gift-signal recipe pushes a `gift_signal` memory fact via this module-push path (not the Brain-turn path). → impact: Stop (gift-signal needs the module-initiated fact-push; referenced as a prereq).
- **DR-a** complete: `QuarantinedReader`/`Extract` — every email-triggered reaction reads the quarantined `Extract`, never raw mail (Seam 7). The `Extract` is produced by the Gmail ingest pre-flight; the reaction callables receive an `Extract` (or its id), never raw body. → impact: Stop (load-bearing untrusted boundary).
- Off-hardware: fakes for emit/dispatcher/CaptureService/create_from_extract/TripAssembler/Maps; deterministic `DomainEvent` fixtures; no model, no Google. → impact: Low.

Simplicity check: each reaction is a thin callable bound to one event_type via a `ReactionRule` — no new infra. A4 is a one-line delegation to `CaptureService`; A5/A7 delegate to `calendar.create_from_extract`; gift-signal delegates to the M4 module fact-push. The only Comms-specific logic is the event→reaction routing table + the A5 Trip/Maps composition. No new store, no new model call beyond what the capabilities already own.

## Prerequisites

- Specs complete: **RXN-emit**, **RXN-rulestore**, **RXN-dispatcher**, **RXN-reconciler** (dispatcher dep), **CAL-create-from-extract**, **TRIP-entity**, **MAPS-connector**, **CaptureService (M8-d-c2)**, **M4-b module fact-push amendment** (ADR-021 dep #1 + gift-signal category), **DR-a**.
- Environment: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` | create | recipes package marker + re-export the per-cluster `register_*` functions |
| `/Users/artemis-build/artemis/src/artemis/reactions/recipes/comms.py` | create | A4/A5/A7/gift async reaction callables (fq recipe-ids) + `register_comms_reactions(registry, *, capture_service, calendar_from_extract_fn, trip_assembler, memory) -> tuple[ReactionRule, ...]` |
| `/Users/artemis-build/artemis/tests/test_reactions_comms.py` | create | A4 inert-suggestion routing, A5 held-event + Trip assembly (airport block is planning's), A7 held-event, gift-signal push, idempotency, canonical-rule shape, Tier-B suggest-not-auto |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: A4 — commitment → inert task suggestion** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/comms.py` —

  `async def react_commitment_to_task(event: DomainEvent, *, capture_service: CaptureService) -> ReactionResult` (ADR-016 async). The dispatcher invokes this on an `email-ingested` event whose payload has `commitment_detected == True`. The reaction:
  1. Reads the quarantined `Extract` referenced by `event.payload["extract_id"]` (NEVER raw mail — Seam 7). Pass `extract.summary` (already laundered) to `CaptureService`.
  2. Calls `await capture_service.suggest_from_text(source="email", text=<extract.summary>, untrusted=True)` — this creates an INERT `suggestions` row (I-1: inert, owner accepts; the existing CaptureService quarantine gate + graduation apply). Do NOT auto-create a task.
  3. Returns `ReactionResult(status="suggested", ref=<suggestion_id or None>, undoable=False)` (a suggestion is already inert; no undo needed).

  **Tier-B registration:** A4 is Tier-B (judgment — "is this a commitment?"). It registers via the rulestore's suggest→graduate path; the *graduation* (auto-suggest without owner re-confirm) is itself the CaptureService capture-recipe graduation (M8-d-c2) — A4 inherits it. The matching canonical `ReactionRule` is `ReactionRule(name="reaction:email_to_task", event_type=EventType.EMAIL_INGESTED, tier=ReactionTier.B, external_effect=False, reaction_ref="reaction:email_to_task", dedup_key_fields=("message_id",))` — the dispatcher composes the stable key from `dedup_key_fields` over the payload so one email (one `message_id`) yields one suggestion even on re-fire. The "only when `commitment_detected==True`" condition is a guard inside the callable (the canonical `ReactionRule` has no per-rule predicate field).

  — done when: `uv run mypy --strict src` passes; `await react_commitment_to_task(event, capture_service=fake)` calls `capture_service.suggest_from_text(source="email", ..., untrusted=True)` exactly once and returns `status="suggested"`; raw mail body is never passed (assert the call arg is the extract summary, not raw text); a re-fire with the same `message_id` is deduped by the dispatcher ledger (assert one suggestion).

- [ ] **Task 2: A5/A7 — flight/meeting email → held-tentative event (A5 with Trip + Maps)** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/comms.py` —

  `async def react_email_to_held_event(event: DomainEvent, *, calendar_from_extract_fn, trip_assembler) -> ReactionResult` (ADR-016 async). Invoked on `EMAIL_INGESTED` with `event.payload["event_kind"] in {"flight", "meeting"}` (guarded inside the callable):
  1. Read the quarantined `Extract` by `event.payload["extract_id"]`.
  2. **A7 (meeting):** call `held = await calendar_from_extract_fn(extract, event_type="meeting")` → a `HeldTentativeEvent` (NOT written to Google — held until approved per I-2/C5=B). Return `ReactionResult(status="held", ref=held.id, undoable=True)`.
  3. **A5 (flight):** route through the Trip assembler first — build a `TripExtract` from the quarantined `Extract` (`kind=TripLegKind.FLIGHT`, `title`/`start_dt`/`end_dt`/`origin`/`destination`/`co_travellers` from the extract scalars, `raw_ref=f"{message_id}:0"`), then `trip_id = trip_assembler.assemble(trip_extract)` (Decision 5: multi-email itinerary → one revisable Trip; the assembler computes the stable key from destination+date-window INTERNALLY — no `trip_key=` kwarg — and EMITS `TRIP_ASSEMBLED`, which fires the RXN-recipes-planning airport-leave block). Then:
     a. Create the held flight event: `held = await calendar_from_extract_fn(extract, event_type="flight")` (`"flight"`/`"meeting"` are the only valid `event_type` values).
     b. **Do NOT create the airport-leave block here** — it is owned by RXN-recipes-planning's `TRIP_ASSEMBLED` reaction (triggered by the assembler's emit in step 3). This removes the earlier double-home and the invented `event_type="airport_buffer"`. (`maps` is therefore not a dependency of this reaction.)
     c. Return `ReactionResult(status="held", ref=held.id, undoable=True)` (the owner approves the held events to write them to Google).

  **Tier-B + held-until-approved:** A5/A7 are Tier-B (judgment). They NEVER auto-write Google — `calendar.create_from_extract` holds the event; the approve→Google write is the GATE-staged external effect (owned by CAL-create-from-extract). The reaction's only effect is creating held-tentatives (internal, reversible → undoable notice) + assembling the Trip. The canonical `ReactionRule` is `ReactionRule(name="reaction:email_to_held_event", event_type=EventType.EMAIL_INGESTED, tier=ReactionTier.B, external_effect=False, reaction_ref="reaction:email_to_held_event", dedup_key_fields=("message_id",), stateful=True)` — `stateful=True` so re-fired itinerary emails (different `message_id` but same Trip via the assembler's internal stable key) revise the Trip without duplicating; the dispatcher dedups per `message_id` for the held event.

  — done when: `uv run mypy --strict src` passes; A7 path returns a `HeldTentativeEvent` ref and never calls a Google-write tool; A5 path builds a `TripExtract` and calls `trip_assembler.assemble(trip_extract)` (single positional arg, no `trip_key=`), creates the held flight event with `event_type="flight"`, and does NOT create an airport block / use `maps` (the planning reaction owns it via the assembler's `TRIP_ASSEMBLED` emit); a re-fed flight extract for the same Trip revises the same Trip (the assembler is idempotent — assert no duplicate Trip).

- [ ] **Task 3: gift-signal memory category + email-to-self clip channel** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/comms.py` —

  `async def react_gift_signal(event: DomainEvent, *, memory) -> ReactionResult` (ADR-016 async). Invoked on `email-ingested` with `event.payload["gift_signal"] == True` (the gift-signal flag is set by the M4 extraction gift-signal category — ADR-021 dep #5):
  1. Read the quarantined `Extract`.
  2. Push a `gift_signal` memory fact via the **module-initiated** `MemoryStore.add_fact` path (ADR-021 dep #1), with `source_kind="module"`, `source_ref=<the email message id>`, and the gift-signal category. The fact records the signal (e.g. "owner's friend X mentioned wanting Y") for later cross-domain recall — NOT a task, NOT an external action.
  3. Return `ReactionResult(status="noted", ref=<fact_id>, undoable=True)`.

  **Email-to-self clip channel (I-11=B, ships now):** define a thin `clip_from_email_to_self(extract) -> str` path: an email the owner sends to themselves (detected by sender==owner) routes its content as a clip into the same gift-signal/capture inbox. The **iOS Share Extension is DEFERRED/Mac-gated** — the email-to-self fallback is the v1 clip channel. Document this split; the email-to-self path reuses the quarantine + CaptureService/memory push (no new channel infra).

  **Tier-B:** gift-signal is a judgment reaction (memory fact, internal/reversible → auto with an undoable notice once graduated; suggest-first before graduation). The canonical `ReactionRule` is `ReactionRule(name="reaction:gift_signal", event_type=EventType.EMAIL_INGESTED, tier=ReactionTier.B, external_effect=False, reaction_ref="reaction:gift_signal", dedup_key_fields=("message_id",))`; the "only when `gift_signal==True`" condition is a guard inside the callable.

  — done when: `uv run mypy --strict src` passes; `await react_gift_signal(event, memory=fake)` calls the module `add_fact` path with `source_kind="module"` and the gift-signal category, returns `status="noted"`; the email-to-self clip path routes a self-addressed email's extract into the capture/memory inbox; no external action is taken; iOS Share Extension is documented as deferred (not built).

- [ ] **Task 4: `register_comms_reactions` wiring** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/comms.py`, `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` —

  `def register_comms_reactions(registry: ToolRegistry, *, capture_service, calendar_from_extract_fn, trip_assembler, memory) -> tuple[ReactionRule, ...]`: registers each async reaction callable in the `ToolRegistry` under its fq `reaction_ref` recipe id (`reaction:email_to_task`, `reaction:email_to_held_event`, `reaction:gift_signal`) via `functools.partial` (injecting the capability handles so each `callable_ref` has the ADR-016 `async (args) -> BaseModel` shape), and returns the three canonical `ReactionRule`s (all `tier=ReactionTier.B`, `external_effect=False`, str `reaction_ref`, `dedup_key_fields=("message_id",)`). All bind to `EventType.EMAIL_INGESTED` (the flag scalars discriminate inside each callable). `maps` is NOT a parameter (the airport block is planning's). Document the event_type→reaction map + the `dedup_key_fields`. Re-export `register_comms_reactions` from `recipes/__init__.py`.

  **I-12 (selective legacy migration):** migrate a legacy Gmail polled push onto this layer ONLY where observability/links/graduation add value (e.g. the urgency briefing stays as-is — it's a dumb notifier; the commitment-detection push migrates to A4 for graduation). Document which legacy pushes migrate and which stay. Do NOT migrate dumb notifiers.

  — done when: `uv run mypy --strict src` passes; `register_comms_reactions(...)` registers 3 reaction callables as tools and returns 3 canonical `ReactionRule`s; all `tier=ReactionTier.B`, `external_effect=False`, str `reaction_ref`, bound to `EventType.EMAIL_INGESTED`; the event_type→reaction map is asserted in tests; `from artemis.reactions.recipes import register_comms_reactions` succeeds.

- [ ] **Task 5: Tests** — files: `/Users/artemis-build/artemis/tests/test_reactions_comms.py` — typed pytest, async (`@pytest.mark.asyncio`).

  Fakes: `FakeCaptureService` (records `suggest_from_text` calls), `FakeCalendarFromExtract` (returns a `HeldTentativeEvent`; records calls; asserts no Google-write), `FakeTripAssembler` (records `assemble(extract)` calls + returns a `trip_id: str`; idempotent — same Trip for the same destination/window), `FakeMemory` (records `add_fact`), a `FakeDispatcher`/`FakeToolRegistry` with an idempotency ledger.

  - **A4 inert suggestion:** an `EMAIL_INGESTED` event with `commitment_detected=True` → `react_commitment_to_task` calls `suggest_from_text(source="email", untrusted=True)` once; the arg is the extract summary, not raw mail; returns `status="suggested"`; a re-fire with the same `message_id` → deduped (one suggestion).
  - **A4 never auto-creates a task:** assert no `task.create` / direct task-creation call — only the inert suggestion.
  - **A7 meeting → held:** returns a `HeldTentativeEvent` ref; `FakeCalendarFromExtract` was called with `event_type="meeting"`; NO Google-write tool called.
  - **A5 flight → Trip + held (no airport block here):** `trip_assembler.assemble(trip_extract)` called with a single positional `TripExtract` (no `trip_key=`); held flight event created with `event_type="flight"`; the reaction does NOT create an airport block and does NOT depend on `maps` (the airport block is RXN-recipes-planning's, fired by the assembler's `TRIP_ASSEMBLED` emit); a re-fed flight extract for the same destination/window revises the same Trip (assert one Trip id).
  - **gift-signal push:** `react_gift_signal` calls the module `add_fact` with `source_kind="module"` + gift category; returns `status="noted"`; email-to-self clip routes into the capture/memory inbox.
  - **Canonical rule shape + Tier-B not auto-enabled:** all three returned `ReactionRule`s carry `tier=ReactionTier.B`, `external_effect=False`, a `str` `reaction_ref`, `dedup_key_fields=("message_id",)`, and `event_type=EventType.EMAIL_INGESTED`; assert none is in `TIER_A_BUILTINS`.
  - **Payload safety:** assert no reaction callable receives raw mail body — only the quarantined extract/summary + ids + scalars.

  — done when: `uv run pytest -q tests/test_reactions_comms.py` passes AND `uv run mypy --strict src tests/test_reactions_comms.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 6 (GATED — on-hardware):** On the Mini with the real reaction infra + Gmail mirror + served model: a real flight email → A5 assembles a Trip, creates a held tentative flight event (NOT on Google until approved), computes a real airport buffer via the real Maps key; a real commitment email → A4 inert suggestion in the inbox; owner approves the held flight → it writes to Google via GATE. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/recipes/comms.py` |
| Create | `/Users/artemis-build/artemis/tests/test_reactions_comms.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_reactions_comms.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_reactions_comms.py` | Test gate (fakes only) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/reactions/recipes/__init__.py`, `src/artemis/reactions/recipes/comms.py`, `tests/test_reactions_comms.py` |
| `git commit` | `"feat: RXN-recipes-comms — A4 commitment→task, A5/A7 email→held-event, gift-signal reactions"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope resolution (off-hardware: tmp_path fixture) |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | Real Maps key + Google write are GATED on-hardware |

## Specialist Context

### Security

- **Quarantine-first (Seam 7):** every email-triggered reaction reads the DR-a `Extract`, never raw mail. The reaction callables receive an `Extract`/summary + ids + scalars — never a raw body. A4 passes `extract.summary` to `CaptureService` (which itself re-gates). Enforced by construction (the callables take an extract id, resolve it to an `Extract`).
- **No auto-external-write:** A5/A7 create HELD tentatives only (I-2/C5=B); the Google write happens only on owner approval, GATE-staged inside CAL-create-from-extract. This spec's reactions have no external-effect surface — they create inert suggestions / held events / memory facts (all internal/reversible).
- **email→task is inert (I-1):** A4 reuses `CaptureService` — a suggestion, never an auto-created task. The owner accepts from the inbox.
- **Tier-B gate:** A4/A5/A7/gift are judgment reactions → Tier-B → suggest→graduate (never auto-enabled). The Tier-A gate (universal∧internal∧reversible∧zero-judgment) structurally excludes them.
- **Payload privacy (Seam 5/7):** `DomainEvent.payload` carries ids + scalars (message_id, commitment_detected, event_kind, gift_signal) — never titles/snippets/bodies. The reaction resolves the extract from the id.

[apex-security review: confirm no reaction callable receives raw mail; confirm A5/A7 never call a Google-write tool directly (only `calendar.create_from_extract` which holds); confirm the gift-signal fact-push is module-sourced (`source_kind="module"`) and the email-to-self clip routes through quarantine.]

### Performance

- Each reaction is a thin async callable dispatched off the heartbeat/Brain — not on the interactive turn. A5's Trip assembly is windowed (re-fires update one Trip). Maps travel-time is one external call (Mac) or a constant (dev/fallback). No per-reaction model call beyond what the capabilities already own.

### Accessibility

(none — headless reaction recipes; the held-event/suggestion surfaces are the client Review/inbox, Wave U)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/recipes/comms.py` | Document each reaction's cluster letter + Tier + idempotency key + the capability it delegates to; document the quarantine-first invariant, held-until-approved (A5/A7), inert-suggestion (A4), gift-signal module-push + email-to-self clip (iOS Share Extension deferred) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_reactions_comms.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_reactions_comms.py` → verify: A4 inert-suggestion via CaptureService (extract summary, not raw mail) + dedup; A4 never auto-creates a task; A7 held meeting event (no Google write); A5 builds a TripExtract + calls `assemble(extract)` (no `trip_key=`) + held flight event, no airport block here (planning owns it) + re-fed extract revises one Trip; gift-signal module fact-push + email-to-self clip; the three returned rules are canonical `ReactionRule` (str `reaction_ref`, `dedup_key_fields`, `EventType.EMAIL_INGESTED`) all `ReactionTier.B` (not in `TIER_A_BUILTINS`); no raw mail to any callable.
- [ ] `uv run python -c "from artemis.reactions.recipes import register_comms_reactions; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) real flight email → Trip + held event + real Maps buffer; commitment email → inert suggestion; approve held → Google write via GATE → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
