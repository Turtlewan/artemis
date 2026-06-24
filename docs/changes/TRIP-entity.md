---
spec: trip-entity
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave R · NEW · de-park Trip (ADR-021 Decision 4/5 + dependency #4). M4-homed beside Place.
     TripIt-style aggregation entity correlating multi-email itineraries into ONE revisable Trip —
     the A5 flight-playbook stateful/windowed proof case (idempotent on a stable key; re-fire updates,
     never duplicates). Co-travel detection links PERSON entities. cross_model_review: true (owned
     SQLCipher data + stateful assembly correctness). -->

# Spec: TRIP-entity — TripIt-style Trip aggregation entity (multi-email itinerary → one revisable Trip)

**Identity:** A Trip aggregation layer M4-homed beside Place: a `trip` SQLCipher table (structured legs + dates, unlike a bare `entities` row) whose Trip is reachable via an `EntityRef` (`module="memory", entity_id="trip:<id>"`), plus a `TripAssembler` that ingests quarantined itinerary `Extract`s and assembles/revises ONE Trip keyed stably on destination+date-window — idempotent stateful/windowed assembly (ADR-021 Decision 5), with co-travel `PERSON` linkage.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (Decision 4/5; dependency #4 — Trip entity + Maps de-park) · docs/findings/cluster-decisions/DECISIONS-LOG.md (I-4/I-5 de-park Trip) · contracts.md Seam 6 (EntityRef/EntityRepository).

## Assumptions

- **M4-d-1** complete: `EntityType`, `EntityRef`, `EntityRepository` (`resolve_or_create_entity(name, entity_type, *, external_ref=None) -> str`, `get_entity`, `list_entities`), `new_entity_id`, `person_fact_key`, and the owned memory SQLCipher DB + `now_iso`/`SENTINEL_TS` are importable from `artemis.memory`. → impact: Stop (Trip rows live in the SAME owner-private memory DB beside `entities`; co-travel PERSON refs resolve via `EntityRepository`).
- **A Trip is NOT a bare entity** — it carries structured legs (flight/hotel/transport), per-leg dates/locations, and a status — so it is a dedicated `trip` table (+ `trip_leg`), NOT an `EntityType` enum value. It is made cross-module-linkable by minting an `EntityRef(module="memory", entity_id=f"trip:{trip_id}")` (a logical pointer per ADR-013 D2 — never a cross-store join). The owning spoke (memory/travel) creates PLACE entities for destinations on demand (Seam 6). → impact: Stop (do NOT add `TRIP` to `EntityType`; the structured shape needs its own table; the Trip is referenced by `EntityRef`, the M4-d-1 pattern for non-PERSON structured things).
- **DR-a** complete: itinerary emails arrive as quarantined `Extract`s (`Extract.summary`, `Extract.claims`) — the assembler reads ONLY the Extract, never raw mail (Seam 7). The flight/hotel fields the assembler needs are parsed from the structured `TripExtract` that the Gmail/Finance quarantine path emits — TRIP-entity defines the `TripExtract` shape it consumes; the email→TripExtract extraction itself rides the Gmail signal path / a Wave-R comms recipe (referenced, not built here). → impact: Stop (TRIP-entity is the ASSEMBLER + STORE; the email parse that produces a `TripExtract` is upstream — this spec defines the input contract and tests it with hand-built `TripExtract`s).
- **Stateful/windowed assembly (ADR-021 Decision 5):** itinerary pieces arrive across multiple emails over a window. Each `TripExtract` is matched to an existing open Trip on a **stable key** (`destination_place_id` + overlapping date-window); a match REVISES the Trip (adds/updates legs), a non-match opens a new Trip. Re-processing the same email leg (same `raw_ref`) is idempotent — never a duplicate leg. → impact: Stop (this is the load-bearing idempotency invariant the tests assert; the stable-key match reuses the Wave-R shared reconciler primitive's posture, but TRIP-entity's leg-dedup is a deterministic `raw_ref` UNIQUE — no fuzzy match needed for the same email).
- **RXN-emit** complete (for the emit seam): `DomainEvent`, `EventType` (now including `EventType.TRIP_ASSEMBLED`) importable from `artemis.reactions`. TRIP-entity emits `TRIP_ASSEMBLED` after each assemble/revise via an injected `Callable[[DomainEvent], None]` (the canonical RXN-emit `Subscriber` shape — `EventBus.emit` IS such a callable). The emitter defaults to a no-op so TRIP-entity builds/tests standalone before RXN-dispatcher wires `EventBus.emit`. TRIP-entity imports `DomainEvent`/`EventType` only — never the dispatcher. → impact: Stop (this is the producer side of the `trip-assembled` event RXN-recipes-planning consumes; payload is scalars only per Seam 5).
- **Off-hardware:** plain-sqlite fallback + `FakeKeyProvider(owner_unlocked=True)`; the assembler is fed hand-built `TripExtract`s (no model, no Gmail). → impact: Low.

Simplicity check: considered modelling Trip as one big `entities.attributes` JSON blob — rejected; legs need per-row dates for the date-window stable-key match + the A5 airport-block reaction, so a `trip` + `trip_leg` relational pair is the minimum. Considered a fuzzy matcher for leg-dedup — rejected; the same email leg carries a stable `raw_ref`, so leg-dedup is a deterministic UNIQUE; the *cross-email Trip* match (which legs belong to the same trip) is the only judgment, and that is destination+date-window, not fuzzy text.

## Prerequisites

- Specs complete: **M4-d-1** (entity backbone + memory DB), **M0-a/M2-b/c** (Settings, KeyProvider, sqlcipher). **DR-a** (Extract) for the input contract. **RXN-emit** (`DomainEvent`/`EventType.TRIP_ASSEMBLED`) for the emit seam. (RXN-reconciler is NOT a hard prereq — Trip's stable-key match is self-contained; the shared reconciler consumes Trip later for co-travel/link-integrity.)
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/memory/trips.py` | create | `TripStatus`, `TripLegKind`, frozen `TripLeg`, `Trip`, `TripExtract`; `trip`/`trip_leg` DDL + `create_trip_schema(conn)`; `TripRepository`; `TripAssembler`; `trip_entity_ref(trip_id) -> EntityRef` |
| `/Users/artemis-build/artemis/src/artemis/memory/__init__.py` | modify | re-export `Trip`, `TripLeg`, `TripExtract`, `TripRepository`, `TripAssembler`, `trip_entity_ref` |
| `/Users/artemis-build/artemis/tests/test_memory_trips.py` | create | schema round-trip; assemble new Trip; revise existing Trip; leg idempotency (same raw_ref); co-travel PERSON link; stable-key match window; EntityRef shape |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Trip schema + value types** — files: `/Users/artemis-build/artemis/src/artemis/memory/trips.py` —

  Enums (TEXT + CHECK): `TripStatus`: `PLANNED="planned"`, `ACTIVE="active"`, `COMPLETED="completed"`, `CANCELLED="cancelled"`. `TripLegKind`: `FLIGHT="flight"`, `HOTEL="hotel"`, `TRANSPORT="transport"`, `OTHER="other"`.

  Frozen Pydantic models (`ConfigDict(frozen=True)`):
  ```python
  class TripExtract(BaseModel):                 # the assembler's INPUT — built from a quarantined Extract upstream
      model_config = ConfigDict(frozen=True)
      kind: TripLegKind
      title: str                                # e.g. "SQ322 SIN→LHR" (already sanitised from the Extract)
      start_dt: str | None                      # ISO-8601
      end_dt: str | None
      origin: str | None                        # place text (assembler resolves → PLACE entity)
      destination: str | None
      confirmation_ref: str | None              # booking/PNR (owner-visible)
      co_travellers: tuple[str, ...] = ()       # names/emails parsed from the itinerary
      raw_ref: str                              # source_message_id:line_index — leg idempotency key

  @dataclass(frozen=True)
  class TripLeg:
      id: str; trip_id: str; kind: TripLegKind; title: str
      start_dt: str | None; end_dt: str | None
      origin_place_id: str | None; destination_place_id: str | None
      confirmation_ref: str | None; raw_ref: str

  @dataclass(frozen=True)
  class Trip:
      id: str; name: str; status: TripStatus
      destination_place_id: str | None
      start_dt: str | None; end_dt: str | None   # span over legs
      traveller_entity_ids: tuple[str, ...]      # PERSON EntityRefs (co-travel)
      legs: tuple[TripLeg, ...]
  ```

  DDL via `create_trip_schema(conn)` (idempotent, FK-on):
  - **`trip`**: `id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','active','completed','cancelled')), destination_place_id TEXT, start_dt TEXT, end_dt TEXT, traveller_ids TEXT NOT NULL DEFAULT '[]'` (JSON array of PERSON entity ids), `created_at TEXT NOT NULL, updated_at TEXT NOT NULL`. Index: `idx_trip_dest` on `(destination_place_id)`, `idx_trip_span` on `(start_dt, end_dt)`.
  - **`trip_leg`**: `id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trip(id) ON DELETE CASCADE, kind TEXT NOT NULL CHECK(kind IN ('flight','hotel','transport','other')), title TEXT NOT NULL, start_dt TEXT, end_dt TEXT, origin_place_id TEXT, destination_place_id TEXT, confirmation_ref TEXT, raw_ref TEXT NOT NULL, created_at TEXT NOT NULL`. **`UNIQUE idx_trip_leg_raw_ref` on `(raw_ref)`** (leg idempotency — re-processing the same email leg never double-inserts). Index: `idx_trip_leg_trip` on `(trip_id)`.

  `def trip_entity_ref(trip_id: str) -> EntityRef`: `return EntityRef(module="memory", entity_id=f"trip:{trip_id}")` (the cross-module pointer; ADR-013 D2).

  — done when: `uv run mypy --strict src` passes; `create_trip_schema` creates both tables + indexes + the `raw_ref` UNIQUE; idempotent re-call; `trip_entity_ref("x").entity_id == "trip:x"`.

- [ ] **Task 2: TripRepository** — files: `/Users/artemis-build/artemis/src/artemis/memory/trips.py` —

  `class TripRepository(conn)`. Parameterised SQL; ids `uuid4().hex`; `now_iso()` timestamps.
  - `create_trip(name, *, destination_place_id=None, start_dt=None, end_dt=None) -> str`.
  - `get_trip(id) -> Trip | None` (joins legs; deserialises `traveller_ids`).
  - `list_trips(*, status=None) -> list[Trip]`.
  - `add_leg(trip_id, leg: TripExtract, *, origin_place_id=None, destination_place_id=None) -> str` — INSERT `trip_leg`; on `raw_ref` UNIQUE collision return the EXISTING leg id (idempotent — `INSERT ... ON CONFLICT(raw_ref) DO NOTHING` then SELECT). After insert, recompute the Trip's `start_dt`/`end_dt` span (min/max over legs) + `updated_at`.
  - `find_open_trip(*, destination_place_id, window_start, window_end) -> Trip | None` — the STABLE-KEY match: an open (`status IN ('planned','active')`) Trip with the same `destination_place_id` AND a date-window that overlaps `[window_start, window_end]`. Returns the single best match (earliest-overlapping) or None.
  - `set_travellers(trip_id, entity_ids: Sequence[str]) -> None` (UNION into `traveller_ids` JSON, dedup).
  - `set_status(trip_id, status) -> None`.

  — done when: `uv run mypy --strict src` passes; `create_trip` + `add_leg` + `get_trip` round-trips a Trip with 2 legs; `add_leg` twice with the same `raw_ref` adds ONE leg; `find_open_trip` matches a same-destination overlapping-window Trip and returns None for a disjoint window.

- [ ] **Task 3: TripAssembler (stateful/windowed assembly)** — files: `/Users/artemis-build/artemis/src/artemis/memory/trips.py` —

  `class TripAssembler` constructed with `(repo: TripRepository, entity_repo: EntityRepository, *, emit: Callable[[DomainEvent], None] = lambda _e: None)`. The `emit` seam is the canonical RXN-emit `Subscriber` shape (`EventBus.emit` satisfies it); it defaults to a no-op so TRIP-entity builds/tests standalone. `from artemis.reactions import DomainEvent, EventType`.

  `def assemble(self, extract: TripExtract) -> str` (sync — pure SQLCipher + entity resolve; no model, no network):
  1. Resolve the destination → PLACE entity: if `extract.destination`, `dest_id = entity_repo.resolve_or_create_entity(extract.destination, EntityType.PLACE)`; else `dest_id = None`.
  2. Resolve origin similarly (`origin_id`).
  3. Find or open the Trip — **stable-key match**: `trip = repo.find_open_trip(destination_place_id=dest_id, window_start=extract.start_dt, window_end=extract.end_dt)`. If `trip is None`: `trip_id = repo.create_trip(name=_trip_name(extract), destination_place_id=dest_id, start_dt=extract.start_dt, end_dt=extract.end_dt)`. Else `trip_id = trip.id` (REVISE the existing Trip — Decision 5).
  4. Add/update the leg: `repo.add_leg(trip_id, extract, origin_place_id=origin_id, destination_place_id=dest_id)` (idempotent on `raw_ref`).
  5. Co-travel: for each name/email in `extract.co_travellers`, `pid = entity_repo.resolve_or_create_entity(name, EntityType.PERSON, external_ref=<email if it looks like one>)`; `repo.set_travellers(trip_id, [pid, ...])` (linked PERSON EntityRefs — co-travel detection).
  6. **Emit `TRIP_ASSEMBLED`** (the producer side of the `trip-assembled` event RXN-recipes-planning consumes). Re-read the assembled `trip = repo.get_trip(trip_id)` (for the current span + leg count), then:
     ```python
     self._emit(DomainEvent(
         event_type=EventType.TRIP_ASSEMBLED,
         source_module="travel",
         entity_refs=(trip_entity_ref(trip_id),),
         payload={
             "trip_id": trip_id,
             "destination_place_id": dest_id or "",
             "start_dt": trip.start_dt or "",
             "end_dt": trip.end_dt or "",
             "leg_count": len(trip.legs),
         },
         occurred_at=now_iso(),
         dedup_key=f"trip-assembled:{trip_id}",
     ))
     ```
     (Payload is scalars only — Seam 5; `dest_id`/spans coerced to `""` when `None` to stay scalar. The dedup_key keys on `trip_id` so re-assembly REVISES rather than duplicates — Decision 5 windowed; the dispatcher's stateful path absorbs the re-fire.)
  7. Return `trip_id`.

  `def _trip_name(extract) -> str`: e.g. `f"Trip to {extract.destination or 'unknown'}"`.

  **Idempotency invariant (inline comment):** `# Re-feeding the same TripExtract (same raw_ref) revises in place — the leg UNIQUE(raw_ref) and the stable-key Trip match guarantee no duplicate Trip and no duplicate leg (ADR-021 Decision 5). The TRIP_ASSEMBLED emit dedups on trip_id so a revision updates the same downstream reaction, never duplicates it.`

  — done when: `uv run mypy --strict src` passes; `assemble(flight_extract)` opens a Trip; `assemble(hotel_extract)` with the same destination + overlapping dates REVISES the SAME Trip (returns the same trip_id, now 2 legs); re-`assemble(flight_extract)` (same raw_ref) does NOT add a duplicate leg; a `TripExtract` with `co_travellers=("Ashley",)` links a PERSON entity to the Trip's `traveller_entity_ids`; an injected `emit` spy receives one `DomainEvent(event_type=EventType.TRIP_ASSEMBLED, ...)` per `assemble` with scalar-only payload and `dedup_key=f"trip-assembled:{trip_id}"`.

- [ ] **Task 4: Tests** — files: `/Users/artemis-build/artemis/tests/test_memory_trips.py` — typed pytest; memory-DB fixture (real keyed SQLCipher → plain-sqlite fallback, M4-d-1 pattern); `EntityRepository(conn, PersonId("owner"))` + `TripRepository(conn)` + `TripAssembler(repo, entity_repo)`.

  - **Schema:** both tables + the `raw_ref` UNIQUE created; idempotent.
  - **Assemble new Trip:** a flight `TripExtract(destination="London", start_dt="2026-08-01T...", raw_ref="m1:0")` → `assemble` returns a trip_id; `get_trip` has 1 leg, `destination_place_id` resolves to a PLACE entity.
  - **Revise existing Trip:** a hotel `TripExtract(destination="London", start_dt="2026-08-02T...", raw_ref="m2:0")` → `assemble` returns the SAME trip_id; `get_trip` now has 2 legs; the Trip span widened.
  - **Leg idempotency:** re-`assemble` the flight extract (same `raw_ref="m1:0"`) → still 2 legs total (no duplicate).
  - **Disjoint window opens a new Trip:** a flight to London six months later (non-overlapping window) → a DIFFERENT trip_id.
  - **Co-travel:** a `TripExtract(co_travellers=("Ashley",))` → the Trip's `traveller_entity_ids` includes the resolved `person:` id; the same person across two legs is deduped (one entity).
  - **EntityRef:** `trip_entity_ref(trip_id).module == "memory"` and `.entity_id == f"trip:{trip_id}"`.
  - **Emit:** construct `TripAssembler(repo, entity_repo, emit=spy)`; `assemble(flight_extract)` calls `spy` once with a `DomainEvent` whose `event_type == EventType.TRIP_ASSEMBLED`, `source_module == "travel"`, `payload["trip_id"] == <trip_id>`, `payload["leg_count"] == 1`, and all payload values scalar; `dedup_key == f"trip-assembled:{trip_id}"`. A revise-assemble emits again with the same `dedup_key` (same trip_id) and updated `leg_count`.

  — done when: `uv run pytest -q tests/test_memory_trips.py` passes AND `uv run mypy --strict src tests/test_memory_trips.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 5 (GATED — on-hardware):** Real keyed SQLCipher trip assembly on the Mini (memory vault mounted, owner unlocked) over real quarantined flight/hotel emails: a multi-email SIN→LHR itinerary assembles into ONE Trip with correct legs + co-travellers; re-running is idempotent. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/memory/trips.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/memory/__init__.py` |
| Create | `/Users/artemis-build/artemis/tests/test_memory_trips.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_memory_trips.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_memory_trips.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/memory/trips.py`, `src/artemis/memory/__init__.py`, `tests/test_memory_trips.py` |
| `git commit` | `"feat: TRIP-entity — itinerary aggregation Trip (stateful assembly + co-travel) de-park"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + memory-DB path resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure SQLCipher + entity resolve; the email→TripExtract parse is upstream |

## Specialist Context

### Security

- Trip rows live in the owner-private memory SQLCipher DB — same wall as facts/entities (`ScopeLockedError` propagates; no plaintext). The assembler reads ONLY a sanitised `TripExtract` built from a DR-a `Extract` — raw itinerary email text never reaches this layer (Seam 7). Co-traveller names resolve through `EntityRepository` (the same person-correlation key as memory). [apex-security/apex-data (cross_model_review): confirm the stable-key match cannot merge two genuinely-different trips (same destination, overlapping window, different travellers) into one — the match is destination+window only; flag whether traveller-set divergence should split a Trip (v1: it does not — documented residual; a future refinement may split on traveller mismatch).]

### Performance

- Trip assembly is a few indexed SQL reads + 1–2 inserts per itinerary leg — sub-ms at personal scale. `find_open_trip` is index-driven on `(destination_place_id, start_dt, end_dt)`. No vectors, no model.

### Accessibility

(none — no frontend; the Trip detail surface is Wave U)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/memory/trips.py` | Document the stable-key assembly (destination+date-window), the leg-idempotency UNIQUE, co-travel PERSON linkage, and the `trip:` EntityRef pointer; note Trip is a table beside Place (not an EntityType) and why |
| Data model | `docs/technical/architecture/data-model.md` | Add the Trip + TripLeg entities (memory scope) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_memory_trips.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_memory_trips.py` → verify: schema; assemble-new; revise-existing (same trip_id, 2 legs); leg idempotency (no dup on same raw_ref); disjoint-window opens new Trip; co-travel links a PERSON entity; `trip_entity_ref` shape; `assemble` emits one `TRIP_ASSEMBLED` `DomainEvent` (scalar payload, `dedup_key=trip-assembled:<id>`) per call.
- [ ] `uv run python -c "from artemis.memory import Trip, TripAssembler, trip_entity_ref; print(trip_entity_ref('x').entity_id)"` → verify: prints `trip:x`.
- [ ] (GATED, on Mini) real multi-email itinerary assembles into one Trip; idempotent → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
