<!-- amended 2026-06-11 per contracts.md (Seam 6) — conformance verified: person_fact_key/EntityRef/EntityRepository/EntityType all match contract exactly; F8 AC python-c note addressed below -->
---
spec: m4-d-1-entity-data-layer
status: ready
token_profile: balanced
autonomy_level: L2
coder_model: codex
---

# Spec: M4-d-1 — Entity data layer (Person/Place/Goal entities + EntityAlias + cross-module EntityRef) in the owner-private memory DB, with `EntityRepository` (resolve/create/alias/merge) and the `subject_entity_id` fact link

**Identity:** Adds the M4 entity backbone DATA layer — three first-class entity types (Person/Place/Goal) homed in the same per-scope SQLCipher memory DB as facts, the `entity_aliases` resolution map (realizing data-model's `EntityAlias`), the `entities.subject_entity_id` link column on the `facts` table, and an `EntityRepository` with resolve-or-create / alias / merge primitives plus the `person_fact_key` cross-module person pointer and the `EntityRef {module, entity_id}` logical reference. Pure key/alias logic — no extraction, no embeddings, no tool surface, no write-path wiring (that is M4-d-2).
→ why: see docs/technical/adr/ADR-013-cross-module-links.md (Decision 1 canonical `person_fact_key`; Decision 3 lifecycle-sync via merge; Decision 6 extend M4 with Person+Place+Goal) · docs/technical/architecture/data-model.md §3 (EntityAlias "my wife"→person/fact reference, person_id-scoped).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

<!-- Split rule: ONE logical phase (the entity DATA layer) touching 3 files (schema modify, entities create, tests create). The schema additions are meaningless without the repository that enforces resolve/merge, and the merge/resolve invariants must be tested together — so DDL + repo + tests are one atomic unit. The tool surface (`memory.resolve_entity`) + write-path wiring (populating `subject_entity_id` during A.U.D.N.) are the separate M4-d-2. Within the 3-file limit; no split needed. -->

## Assumptions
- M4-a is complete and provides the exact symbols this spec consumes: `memory/schema.py` (`create_schema(conn, *, embedder_model_id, dimension)`, `SENTINEL_TS`, `now_iso()`, the `facts` table DDL, the `relation_cardinality` registry); `memory/repository.py` (`BitemporalRepository(conn, person_id)`, frozen `FactRow`, `compute_fact_key`, `as_of`); `memory/engine.py` (`open_memory_db(db_path, key, *, embedder_model_id, dimension, create=True)`); `memory/store.py` (`SqliteMemoryStore`); `memory/__init__.py` (the re-export hub). → impact: Stop (this spec modifies `schema.py`, creates `entities.py`, and re-exports through the same `__init__.py`; all symbols above must exist exactly).
- `PersonId = NewType("PersonId", str)` is defined in `artemis.ports.types` (M0-d) and imported by M4-a. `EntityRepository` takes a `person_id: PersonId` mirroring `BitemporalRepository`'s constructor shape. → impact: Stop (the constructor signature and type import must match M0-d/M4-a).
- M4-a's `compute_fact_key` is a `BitemporalRepository` METHOD (cardinality-aware, hashes `person_id,subject,relation[,object]`) — it is the LOGICAL-FACT key for fact versioning, a DIFFERENT concern from this spec's module-level `person_fact_key` (the cross-module PERSON entity key, keyed on email/UUID per ADR-013 Decision 1). They share the `person:`-style naming intent but are NOT the same function and do NOT collide. → impact: Caution (do NOT reuse or shadow M4-a's `compute_fact_key`; `person_fact_key` is new, module-level, in `entities.py`).
- The memory DB is the per-scope SQLCipher file opened keyed via M4-a's `open_memory_db` (which goes through M2-c `sqlcipher_open` + `cipher_memory_security`). Entities/aliases live in THIS SAME keyed file — no new store, no new key path. → impact: Stop (consume M4-a's keyed open; never create a plaintext entity file).
- Off-hardware test fixture: reuse M4-a's `tests/test_memory_bitemporal.py` fixture approach — try the real keyed `open_memory_db` against a `tmp_path` SQLCipher file with a fixed 32-byte `SecretKey`; if the SQLCipher binding is not importable, FALL BACK to a plain sqlite connection (same DDL, no `PRAGMA key`). The entity layer needs NO embeddings and NO model calls, so a fixed test `person_id` + the DB connection is the entire fixture. → impact: Caution (copy M4-a's fixture skeleton; entity tests are fully deterministic).
- `create_schema` is idempotent (`IF NOT EXISTS`). Adding the two new tables + the `subject_entity_id` column to the `facts` DDL means the column is part of the `CREATE TABLE IF NOT EXISTS facts (...)` statement — for a fresh DB it is created; M4-a has not shipped to any persisted DB yet (build-time, no migration of existing data needed). → impact: Caution (add the column INSIDE the existing `facts` DDL string in `create_schema`, NOT via a separate `ALTER TABLE`; verify M4-a's `facts` DDL is a single `CREATE TABLE IF NOT EXISTS` string before editing).

Simplicity check: considered a separate entity store/DB — rejected by ADR-013 (privacy clincher: a separate registry would cross scopes; M4 already lives owner-private behind the M2 wall). Considered per-type entity tables (persons/places/goals) — rejected: one `entities` table with an `entity_type` discriminator + a nullable JSON `attributes` blob keeps Place/Goal minimal now and extensible without migration (ADR-013 Decision 6 defers their detailed schema). Considered a hard FK from `facts.subject_entity_id` to `entities.entity_id` — rejected: M4-a keeps fact writes FK-free for append speed (same rationale as `source_turn_id`); the link is a plain indexed column populated by M4-d-2. This is the minimum entity substrate the M4-d-2 tool + write-path sit on.

## Prerequisites
- Specs that must be complete first: **M4-a** (`memory/schema.py`, `memory/repository.py`, `memory/engine.py`, `memory/store.py`, `memory/__init__.py` — the entire two-store substrate + keyed open + test fixture). Transitively: M0-a, M0-d, M2-b, M2-c (consumed via M4-a; not touched here).
- Environment setup required: none beyond M4-a's (the same `sqlite-vec` + SQLCipher binding, or the plain-sqlite fallback). No new packages.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/memory/schema.py | modify | Add `entities` + `entity_aliases` tables to `create_schema` (idempotent `IF NOT EXISTS`, `source` CHECK); add the nullable `subject_entity_id TEXT` column to the existing `facts` DDL string + a `PRAGMA table_info` stale-DB guard; add index on `entities(entity_type)`, the UNIQUE partial index on `entities(external_ref)` WHERE `external_ref IS NOT NULL`, index on `entity_aliases(entity_id)`, and the composite index on `facts(subject_entity_id, tx_to, valid_to)` |
| /Users/artemis-build/artemis/src/artemis/memory/entities.py | create | `EntityType(StrEnum)`; frozen `EntityRow`; frozen `EntityRef`; `person_fact_key`; `new_entity_id`; `EntityRepository(conn, person_id)` with resolve_or_create_entity / resolve_alias / add_alias / list_aliases / get_entity / list_entities / merge_entities; `OwnerEntityError` + typed exceptions; re-export `EntityType`/`EntityRow`/`EntityRef`/`EntityRepository`/`person_fact_key` from `memory/__init__.py` |
| /Users/artemis-build/artemis/tests/test_memory_entities.py | create | Deterministic typed pytest reusing M4-a's memory-DB fixture: resolve_or_create idempotency (name + email-keyed), alias resolution, PLACE/GOAL creation, `merge_entities` repoints aliases + `facts.subject_entity_id` and deletes the merged row, `get_entity` KeyError-on-miss, `EntityRef` port/type assertions |

## Tasks

- [ ] Task 1: Schema additions for entities + aliases + the fact link — files: `/Users/artemis-build/artemis/src/artemis/memory/schema.py` —
  In `create_schema`, after the existing `facts` table is created, add (all `IF NOT EXISTS`, substitute no runtime values — these are static DDL):
  - `entities` table:
    ```sql
    CREATE TABLE IF NOT EXISTS entities (
      entity_id TEXT PRIMARY KEY,
      entity_type TEXT NOT NULL CHECK(entity_type IN ('person','place','goal')),
      canonical_name TEXT NOT NULL,
      external_ref TEXT,
      attributes TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    ```
    (`attributes` = nullable JSON blob for deferred type-specific fields — keeps Place/Goal minimal now, extensible without migration per ADR-013 Decision 6.)
  - `entity_aliases` table:
    ```sql
    CREATE TABLE IF NOT EXISTS entity_aliases (
      alias TEXT PRIMARY KEY,
      entity_id TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'extracted' CHECK(source IN ('seed','extracted','owner'))
    )
    ```
    (`alias` is stored already-normalized/lowercased by the repository; the `source` CHECK constrains the closed set at the DB layer — consistent with `entities.entity_type`; adding a future source value is a minor additive migration.)
  - Single-owner scoping note: `entities`/`entity_aliases` carry NO `person_id` column because the memory DB is **one keyed file per scope** (M4-a per-scope partition) — the file IS the owner boundary. `EntityRepository`'s `person_id` arg is carried for API symmetry with `BitemporalRepository`, not for row-level filtering. (If multi-owner-per-file is ever introduced, add `person_id TEXT NOT NULL` then.)
  - Add the nullable column to the EXISTING `facts` `CREATE TABLE IF NOT EXISTS facts (...)` DDL string (NOT a separate `ALTER TABLE`): append `, subject_entity_id TEXT` before the closing paren (place it after `linked_ids TEXT`). Document inline: "links a fact's subject to an entity; POPULATED by M4-d-2, nullable here."
  - Indexes (each `CREATE INDEX IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS`):
    - `idx_entities_type` on `entities(entity_type)`.
    - `idx_entities_external_ref` UNIQUE on `entities(external_ref)` WHERE `external_ref IS NOT NULL` (partial unique — one entity per external ref).
    - `idx_entity_aliases_entity` on `entity_aliases(entity_id)`.
    - `idx_facts_subject_entity` **composite** on `facts(subject_entity_id, tx_to, valid_to)` — covers the M4-d-2 `facts_for_entity` predicate (entity equality + the two open-interval range checks) so the hot cross-module read stays index-driven, not a row-scan after the entity filter.
  - **Stale-DB guard (in `create_schema`, after the DDL block):** run `PRAGMA table_info(facts)` and if `subject_entity_id` is NOT among the columns, `raise RuntimeError("facts.subject_entity_id missing — a pre-M4-d-1 facts table exists; the IF NOT EXISTS DDL skipped the column")`. This converts the silent-skip case (a persisted pre-M4-d-1 `facts` table where `CREATE TABLE IF NOT EXISTS` no-ops the amended DDL) into a loud error. (The 'no persisted DB yet' assumption holds — CI/tests use `:memory:` or `tmp_path` fresh files — but the guard surfaces any violation rather than silently dropping the column.)
  - Note (no extra index): `canonical_name` is NEVER queried directly — resolution always goes through `entity_aliases.alias` (PK) — so no `canonical_name` index is needed; the partial UNIQUE index on `external_ref` is compatible with the equality predicate `WHERE external_ref = ?` used in `resolve_or_create_entity` step (1).
  — done when: `create_schema` on a fresh connection creates `entities` and `entity_aliases` (verify via `SELECT name FROM sqlite_master WHERE type='table'`), the `facts` table has a `subject_entity_id` column (verify via `PRAGMA table_info(facts)`), the composite + partial-unique + alias + type indexes exist (verify via `SELECT name FROM sqlite_master WHERE type='index'`), and `create_schema` against a connection whose `facts` table lacks the column raises the stale-DB `RuntimeError`; `uv run mypy --strict src` passes.

- [ ] Task 2: The entity module — `entities.py` + `__init__` re-exports — files: `/Users/artemis-build/artemis/src/artemis/memory/entities.py`, `/Users/artemis-build/artemis/src/artemis/memory/__init__.py` —
  In `entities.py`:
  - `from enum import StrEnum`; `class EntityType(StrEnum): PERSON = "person"; PLACE = "place"; GOAL = "goal"`.
  - `@dataclass(frozen=True) class EntityRow` mirroring the `entities` row: `entity_id: str`, `entity_type: EntityType`, `canonical_name: str`, `external_ref: str | None`, `attributes: str | None`, `created_at: str`, `updated_at: str`.
  - `@dataclass(frozen=True) class EntityRef`: `module: str`, `entity_id: str` (the ADR-013 Decision-2 logical pointer; for memory-homed entities `module == "memory"`).
  - Exceptions: `class OwnerEntityError(Exception)` (base); raise a `KeyError` from `get_entity` on a missing id (per the contract below). Add any other typed exception only if a method below needs it (e.g. `merge_entities` on a missing id may raise `KeyError`).
  - `def _normalize(text: str) -> str`: strip + lowercase, then **validate at this boundary** — raise `ValueError` if the result contains a NUL byte (`"\x00"`, a SQLite TEXT terminator hazard) or exceeds `MAX_ENTITY_TEXT = 255` chars (length cap on alias/canonical_name/external_ref to stop an extracted-content payload bloating the row or surfacing in logs). The single normalization used for aliases AND for external_ref hashing — keep ONE helper. (Security: entity names/aliases originate from extracted, untrusted turn content — this is the validate-at-write-boundary guard.)
  - `def person_fact_key(*, external_ref: str | None, name: str) -> str`:
    - if `external_ref` is not None and not empty after `_normalize`: `return "person:" + hashlib.sha256(_normalize(external_ref).encode("utf-8")).hexdigest()`.
    - else: `return "person:" + uuid.uuid4().hex`.
    - Docstring: same email ⇒ same key across modules (ADR-013 Decision 1 cross-module person pointer); a name-only person gets a fresh stable UUID key, reused thereafter via alias resolution; if an email is later learned, `merge_entities` repoints the name-only entity onto the email-keyed one (Decision 3 lifecycle). NOTE in the docstring: sha256 here is a **stable deterministic identity-correlation key, NOT a password/secret hash** — the underlying email is separately protected by the SQLCipher wall; do not flag this as a password-hashing violation.
  - `def new_entity_id(entity_type: EntityType) -> str`: `return f"{entity_type.value}:" + uuid.uuid4().hex` (for PLACE/GOAL; PERSON uses `person_fact_key`).
  - `class EntityRepository`:
    - `def __init__(self, conn, person_id: PersonId) -> None`: store both; do all writes in one transaction per method (mirror `BitemporalRepository`); timestamps via `now_iso()` (import from `.schema`).
    - `def resolve_or_create_entity(self, name: str, entity_type: EntityType, *, external_ref: str | None = None) -> str`:
      lookup order — (1) if `external_ref` is not None, `SELECT entity_id FROM entities WHERE external_ref = ?` with the normalized ref; if found return it. (2) else `resolve_alias(name)`; if found return that `entity_id`. (3) else CREATE: derive `entity_id` (`person_fact_key(external_ref=external_ref, name=name)` for `EntityType.PERSON`, `new_entity_id(entity_type)` for PLACE/GOAL); `INSERT INTO entities (entity_id, entity_type, canonical_name, external_ref, attributes, created_at, updated_at)` with `canonical_name=name`, normalized `external_ref` (or None), `attributes=None`, both timestamps `now_iso()`; then seed an alias `add_alias(name, entity_id, source='extracted')`. The alias seed MUST occur in the same create branch (step 3), immediately after the INSERT, so the NEXT call's step (2) `resolve_alias(name)` hits it and returns the same id — do NOT reorder create-before-alias-seed or the second call mints a fresh id. Return `entity_id`. Idempotent: same `name`+`entity_type` (no external_ref) ⇒ resolves the seeded alias ⇒ same id; same `external_ref` ⇒ matches step (1) ⇒ same id.
    - `def resolve_alias(self, text: str) -> str | None`: `SELECT entity_id FROM entity_aliases WHERE alias = ?` with `_normalize(text)`; return the id or None.
    - `def add_alias(self, alias: str, entity_id: str, *, source: str = "extracted") -> None`: UPSERT — `INSERT INTO entity_aliases (alias, entity_id, source) VALUES (?,?,?) ON CONFLICT(alias) DO UPDATE SET entity_id=excluded.entity_id, source=excluded.source` with `_normalize(alias)`.
    - `def list_aliases(self, entity_id: str) -> list[str]`: the REVERSE lookup (all aliases pointing at an entity) — `SELECT alias FROM entity_aliases WHERE entity_id = ? ORDER BY alias`; return the normalized alias strings. (Consumed by M4-d-2's `resolve_entity` tool to populate its `aliases` list.)
    - `def get_entity(self, entity_id: str) -> EntityRow`: `SELECT ...` one row; if none, `raise KeyError(entity_id)`; else build and return `EntityRow` (coerce `entity_type` via `EntityType(...)`).
    - `def list_entities(self, entity_type: EntityType | None = None) -> list[EntityRow]`: `SELECT ...` all rows, optionally `WHERE entity_type = ?`; return `list[EntityRow]`.
    - `def merge_entities(self, *, keep: str, merge: str) -> None`: **guards first** — if `keep == merge` raise `ValueError("cannot merge an entity into itself")`; call `self.get_entity(keep)` and `self.get_entity(merge)` (both raise `KeyError` on a missing id — converts a silent 0-row no-op into a deterministic error). Then in ONE transaction — (1) `UPDATE entity_aliases SET entity_id = ? WHERE entity_id = ?` (merge→keep); (2) `UPDATE facts SET subject_entity_id = ? WHERE subject_entity_id = ?` (merge→keep); (3) the merged entity's own canonical_name alias is already repointed by step (1); (4) `DELETE FROM entities WHERE entity_id = ?` (the merge row). No orphans: aliases + fact links survive on `keep`; the `merge` entities row is removed. Docstring: used when a name-only person later resolves to an email-keyed identity (ADR-013 Decision 3 lifecycle); non-destructive to facts (repoints, never deletes a fact row); **the `merge` entities row deletion is irreversible** (its `canonical_name`/`external_ref`/`attributes` are gone — the guards above are the safety net; ids only in any log, never names).
    - All SQL parameterised (no value interpolation).
  In `memory/__init__.py`: add re-exports `EntityType`, `EntityRow`, `EntityRef`, `EntityRepository`, `person_fact_key` (and add them to `__all__` if M4-a's `__init__.py` declares one).
  — done when: `uv run mypy --strict src` passes; `python -c "from artemis.memory.entities import person_fact_key; a=person_fact_key(external_ref='A@B.com', name='x'); b=person_fact_key(external_ref='a@b.com', name='y'); assert a==b and a.startswith('person:'); c=person_fact_key(external_ref=None, name='x'); assert c.startswith('person:') and c!=a"` exits 0; `python -c "from artemis.memory import EntityType, EntityRow, EntityRef, EntityRepository, person_fact_key"` exits 0.

- [ ] Task 3: Entity-layer tests — files: `/Users/artemis-build/artemis/tests/test_memory_entities.py` — typed pytest. A fixture opens a memory DB by copying M4-a's `tests/test_memory_bitemporal.py` fixture skeleton (try real keyed `open_memory_db` against a `tmp_path` SQLCipher file with a fixed 32-byte test `SecretKey` — annotate it `# TEST KEY ONLY — never use outside tests`; on import failure fall back to a plain sqlite connection with the same DDL, no `PRAGMA key`). Use a fixed test `person_id = PersonId("owner")`. NO embedder, NO model calls. Construct `repo = EntityRepository(conn, person_id)`. Tests:
  - **resolve_or_create idempotency (name-only):** `id1 = repo.resolve_or_create_entity("Alice", EntityType.PERSON)`; `id2 = repo.resolve_or_create_entity("alice", EntityType.PERSON)` (case-insensitive via normalized alias); assert `id1 == id2` and `id1.startswith("person:")`; assert exactly one `entities` row.
  - **email-keyed person stable across calls:** `e1 = repo.resolve_or_create_entity("Bob", EntityType.PERSON, external_ref="Bob@X.com")`; `e2 = repo.resolve_or_create_entity("Robert", EntityType.PERSON, external_ref="bob@x.com")`; assert `e1 == e2` (same external_ref ⇒ same id even with a different name); assert `e1 == person_fact_key(external_ref="bob@x.com", name="Bob")`.
  - **alias resolution:** after creating "Alice", `repo.add_alias("my wife", id1, source="owner")`; assert `repo.resolve_alias("My Wife") == id1`; assert a miss returns None (`repo.resolve_alias("nobody") is None`); assert `set(repo.list_aliases(id1)) == {"alice", "my wife"}` (the seeded canonical-name alias + the added one; both normalized).
  - **PLACE / GOAL creation:** `p = repo.resolve_or_create_entity("Home", EntityType.PLACE)`; `g = repo.resolve_or_create_entity("Run a marathon", EntityType.GOAL)`; assert `p.startswith("place:")` and `g.startswith("goal:")`; assert `repo.get_entity(p).entity_type == EntityType.PLACE`; assert `len(repo.list_entities(EntityType.PLACE)) == 1`.
  - **merge_entities repoints aliases + facts + deletes merged row:** create a name-only person `m = resolve_or_create_entity("Jim", PERSON)` and an email-keyed `k = resolve_or_create_entity("James", PERSON, external_ref="jim@x.com")`; add an alias on `m`; seed a couple of `facts` rows directly via SQL with `subject_entity_id = m` (insert minimal rows — `fact_id`, `fact_key`, `person_id`, `subject`, `relation`, `object`, `confidence`, the bitemporal stamps using `SENTINEL_TS`/`now_iso`, and `subject_entity_id`); call `repo.merge_entities(keep=k, merge=m)`; assert (a) the `m` alias now resolves to `k`, (b) `SELECT count(*) FROM facts WHERE subject_entity_id = m` is 0 and `... = k` equals the seeded count, (c) `repo.get_entity(m)` raises `KeyError`, (d) `repo.get_entity(k)` still succeeds.
  - **merge_entities guards:** `with pytest.raises(ValueError): repo.merge_entities(keep=k, merge=k)` (self-merge); `with pytest.raises(KeyError): repo.merge_entities(keep=k, merge="person:does-not-exist")` (missing merge id → deterministic error, not a silent no-op).
  - **get_entity KeyError on miss:** `with pytest.raises(KeyError): repo.get_entity("person:does-not-exist")`.
  - **input hygiene:** `with pytest.raises(ValueError): repo.resolve_or_create_entity("x"*256, EntityType.PERSON)` (over the 255 cap); `with pytest.raises(ValueError): repo.resolve_or_create_entity("a\x00b", EntityType.PERSON)` (NUL byte).
  - **EntityRef port/type assertions:** `ref = EntityRef(module="memory", entity_id=id1)`; assert `ref.module == "memory"` and `ref.entity_id == id1`; assert `EntityRef` is frozen (`with pytest.raises(...): ref.module = "x"` — `dataclasses.FrozenInstanceError`).
  — done when: `uv run pytest -q tests/test_memory_entities.py` passes AND `uv run mypy --strict src tests/test_memory_entities.py` passes.

## Wave plan
- **Wave 1:** [Task 1 (schema additions), Task 2 (entities.py + re-exports)] — independent: Task 2's module code references the new tables only at runtime, so it is authored in parallel with the Task 1 DDL.
- **Wave 2:** [Task 3 (tests)] — depends on both (the fixture exercises the schema + the repository together).

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/memory/entities.py, /Users/artemis-build/artemis/tests/test_memory_entities.py |
| Modify | /Users/artemis-build/artemis/src/artemis/memory/schema.py, /Users/artemis-build/artemis/src/artemis/memory/__init__.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_memory_entities.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_memory_entities.py` | Test gate (real keyed DB or plain-sqlite fallback) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/memory/schema.py, src/artemis/memory/entities.py, src/artemis/memory/__init__.py, tests/test_memory_entities.py |
| `git commit` | "feat: M4-d-1 entity data layer (Person/Place/Goal + EntityAlias + EntityRef) on the owner-private memory DB" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (paths) — inherited via M4-a's fixture; no new variable |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package install; reuses M4-a's dependency set |

## Specialist Context
### Security
Entities and aliases live in the **owner-private SQLCipher memory DB** — the SAME keyed file as facts, behind the SAME M2/M4-a crypto wall. This spec introduces **no new store and no new key path**: it consumes M4-a's keyed `open_memory_db` connection. Entity `canonical_name`, `external_ref` (emails), and `entity_aliases.alias` ("my wife") are **sensitive owner data** — never log them at info level (redact in any debug output). `merge_entities` is **non-destructive to facts**: it repoints `facts.subject_entity_id`, it never deletes a fact row (only the redundant `entities` row of the merged identity). `person_fact_key` hashes the email (sha256) for the id, but `entities.external_ref` **does store the normalized email in cleartext inside the encrypted DB** — this is an **accepted single-layer (SQLCipher-wall) defence**, consistent with how every fact `object` / episode `text` already lives cleartext in the same keyed store; the email must be readable to display and to drive the `external_ref` dedup lookup, so an HMAC token is not used. Residual risk: if the SQLCipher key is ever compromised the emails are readable — the same blast radius as all owner memory, no worse. Input hygiene: `_normalize` caps length (255) and rejects NUL bytes at the write boundary (entity names come from untrusted extracted turn content). All exceptions exposed outside the module (`KeyError`, `ValueError`) carry **only the `entity_id`, never the raw `canonical_name`/`alias`/`external_ref`** (no sensitive plaintext in tracebacks/logs). [FLAG for apex-security (M4 gate): confirm entity/alias data inherits the M4 owner-private wall (same keyed file as facts, no plaintext entity file ever created); confirm no entity `canonical_name`/`external_ref`/`alias` plaintext is logged or embedded in exception messages.]

### Performance
Alias and external_ref lookups are **indexed point lookups** at per-person scale (thousands of entities) — trivial. `merge_entities` is a **bounded transaction** (two indexed `UPDATE`s + one `DELETE`, all keyed on indexed columns: `entity_aliases(entity_id)`, `facts(subject_entity_id)`, `entities(entity_id)` PK). No N+1, no scans. This is the data layer for ADR-013's hot `memory.resolve_entity` read-path (the tool itself is M4-d-2); the indexes added here make that path index-driven.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/memory/entities.py | Type + docstring all exports; document the `person_fact_key` cross-module person-pointer contract (same email ⇒ same key; name-only ⇒ stable UUID reused via alias; email-later ⇒ merge repoints), the `EntityRef {module, entity_id}` logical reference, alias normalization (lowercase/strip), and `merge_entities` being non-destructive to facts |
| Inline | src/artemis/memory/schema.py | Document `entities`/`entity_aliases` purpose + the nullable `facts.subject_entity_id` link (populated by M4-d-2) |
| Conceptual model | docs/technical/architecture/data-model.md | ✅ ALREADY reconciled in planning (this session): §3 Memory now carries the `Entity` (person/place/goal) + `EntityAlias` + `SemanticFact.subject_entity_id` soft link + the text-ER. **No build-time doc edit needed.** |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_memory_entities.py` → verify: exit 0.
- [ ] (F8 fix) The `python -c` in-memory check CANNOT pass using stdlib `sqlite3.connect(':memory:')` because `create_schema` creates the `vec0` virtual table requiring sqlite-vec loaded (and a plain stdlib connection needs `enable_load_extension` plumbing the command omits). **Use the pytest gate below as the primary gate.** The `python -c` variant is deleted as a primary AC; it may be run as an informational smoke test only on a connection that has sqlite-vec pre-loaded (via the fixture's `load_sqlite_vec` helper).
- [ ] Run `uv run pytest -q tests/test_memory_entities.py` → verify: resolve_or_create idempotency (name + email-keyed), alias resolution + miss→None, PLACE/GOAL creation, `merge_entities` repoints aliases + `facts.subject_entity_id` and deletes the merged row, `get_entity` KeyError on miss, `EntityRef` port/frozen assertions all pass.
- [ ] Run `uv run python -c "from artemis.memory import EntityType, EntityRow, EntityRef, EntityRepository, person_fact_key; print(person_fact_key(external_ref='A@B.com', name='x') == person_fact_key(external_ref='a@b.com', name='y'))"` → verify: prints `True`. (Distinct from the deleted line-172 check: this is import-only — it imports `from artemis.memory` and calls the pure `person_fact_key` function, with NO `create_schema` and NO DB connection, so it needs no sqlite-vec and WILL pass off-hardware.)
- [ ] Run `uv run ruff check . ; uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_
