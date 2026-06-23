<!-- amended 2026-06-11 per contracts.md (Seam 6) + m3-m4-knowledge-memory.md BLOCKs B3, FLAGs F2, F3, F5, F11, UPGRADE U5 -->
<!-- amended 2026-06-17: EmbeddingModel port split embed→embed_documents/embed_query (embedding-layer decision; research/2026-06-17-embedding-implementation.md) -->
---
spec: m4-a-store-schema-bitemporal-repo
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M4-a — Two-store memory schema (bitemporal episodic + semantic) in SQLCipher + sqlite-vec/FTS5 inside the per-scope vault, the `MemoryStore` adapter skeleton, and the bitemporal repository layer (with golden tests for `as_of` / idempotency / interval-closing)

**Identity:** Builds the on-disk memory substrate for one person: a per-scope SQLCipher database (opened via the M2-c keyed open) holding two loosely-coupled stores — a four-timestamp **bitemporal episodic** event log and a **semantic** (subject,relation,object) fact table with **sqlite-vec** vectors + **FTS5** hybrid recall — plus the bitemporal repository that applies non-destructive ADD/UPDATE(close-interval+insert)/DELETE(tombstone) operations and the `as_of(valid_t, tx_t)` filter, behind a partial `MemoryStore` adapter skeleton. The write-path *decisioning* (extraction + A.U.D.N.) is M4-b; recall ranking / auto-inject / decay / owner surface is M4-c.
→ why: see docs/technical/adr/ADR-004-memory-engine.md (bitemporal 4-timestamp; sqlite-vec-in-SQLCipher; per-person partition; never-hard-delete) · docs/research/memory-engine-research.md (required mitigations: golden tests for as_of/idempotency/interval-closing).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

<!-- Split rule: ONE logical phase (the storage substrate + the bitemporal repository it is tested through) but it creates >3 files (schema/DDL, the sqlite-vec+SQLCipher open helper, the bitemporal repository, the partial MemoryStore adapter skeleton, the golden tests). Justified atomic exception: the DDL is meaningless without the repository that enforces its interval invariants, and the golden tests (the ADR-required mitigation) must exercise BOTH together — splitting DDL from the repo would leave a schema no test can prove correct. The decisioning write-path is the separate M4-b; recall/inject/decay/owner is the separate M4-c. Flagged per rules. -->

## Assumptions
- M0-a (`config.Settings`, `paths.scope_dir`), M0-d (`ports`: `MemoryStore`, `Fact`, `PersonId`, `Scope`, `AsOf`, `Vector`, `EmbeddingModel`), M2-b (`ScopedStore`, `ScopedConnection`, `KeyProvider`, `SecretKey`, `ScopeLockedError`, `CrossScopeError`, `paths` scope dirs), M2-c (`sqlcipher_open(path, key_hex)` raw-hex keyed open + `cipher_memory_security`) are complete. → impact: Stop (this spec consumes those exact symbols; the keyed DB open goes through M2-c's `sqlcipher_open`, the wall/key seam through M2-b).
- The memory DB path is **exactly the M2-b location**: `paths.scope_dir(settings, scope) / "memory" / "memory.db"` (M2-b Task 3 `ScopedStore.db_path()` already names this). M4-a does NOT invent a new path — it opens the file M2-b's `ScopedConnection` points at, keyed by the scope's DEK. → impact: Stop (the file location is the M2-b contract; reuse `ScopedConnection.db_path` / `ScopedConnection.open(key)`).
- **The memory DB is opened keyed via M2-c `sqlcipher_open`**, NOT plain sqlite3 — born encrypted inside the per-scope vault. Per-person partition = one keyed file per scope (a guest scope cannot open the owner file: no key). → impact: Stop (no plaintext memory file is ever created; the wall is cryptographic).
- The SQLCipher Python binding chosen at the M2-c spike is **APSW + apsw-sqlite3mc** (ADR-004's lean for the sqlite-vec combo). sqlite-vec is loaded as a **loadable C extension** on the keyed connection (`conn.enableloadextension(True); conn.loadextension(<sqlite_vec path>)`). The exact binding + the sqlite-vec-under-SQLCipher load is an ADR-004 build-time spike. → impact: Stop. [RESOLVED — GATED Task 1: M2-c Task 3 left the binding behind a `sqlcipher_open(path, key_hex) -> Connection` seam and named `sqlcipher3-binary` OR `APSW+sqlite3mc` as alternatives, deferring the final choice to "the M4 sqlite-vec spike" — this IS that spike (Task 1 below, GATED). The two bindings differ in the extension-load API (`conn.enableloadextension`/`loadextension` on APSW vs `conn.enable_load_extension`/`load_extension` on sqlcipher3). Drafting against the APSW API behind a thin `load_sqlite_vec(conn)` helper in `memory/engine.py` so the binding stays swappable; CONFIRM the binding at Task 1 and adjust the two extension-load calls if sqlcipher3 was chosen. Does not change the schema or repository shape.]
- The **embedding dimension is locked in store metadata** (brain.md "dimension locked in store metadata; model change = explicit re-index migration"). M4-a writes `embedder_model_id` + `dimension` into a `meta` table on DB creation and the sqlite-vec virtual table is declared with that fixed dimension; inserting a vector of a different length raises a typed `DimensionMismatchError`. → impact: Stop (dimension-lock is an ADR/brain.md invariant; mirrors M3-a's LanceDB dimension-lock).
- **Bitemporal model = four timestamps** per fact-version row: `valid_from`, `valid_to` (the real-world validity interval — half-open `[valid_from, valid_to)`), `tx_from`, `tx_to` (the ingestion/system interval — half-open `[tx_from, tx_to)`). "Current" / open intervals use a **sentinel max timestamp** (`9999-12-31T23:59:59Z`) for `valid_to`/`tx_to`, NOT NULL (so range predicates and the partial unique index stay simple and index-friendly — the ADR-004 "classic AI-codegen silently-wrong trap" guard). All timestamps stored as **ISO-8601 UTC text** (lexicographically sortable; SQLite has no native datetime). → impact: Stop (the sentinel-not-NULL + half-open convention is the load-bearing correctness decision the golden tests assert). (This is the Graphiti four-timestamp bitemporal schema — ADR-004 reference: valid_from/valid_to = event-time t_valid/t_invalid; tx_from/tx_to = ingestion-time t'_created/t'_expired.)
- `as_of(valid_t, tx_t)` recall = the WHERE predicate `valid_from <= valid_t AND valid_t < valid_to AND tx_from <= tx_t AND tx_t < tx_to`. `AsOf=None` (M0-d default) → both = `now()`. This selects, for each `fact_key`, the at-most-one row that was believed-true at `tx_t` about the world at `valid_t`. → impact: Stop (this is the bitemporal recall contract the golden tests assert).
- A **`fact_key`** identifies a logical fact across its version rows (so UPDATE closes the prior version of the SAME key and inserts a new one). `fact_key` = a stable hash of `(person_id, subject, relation)` for SINGLE-cardinality relations (MULTI relations add `object` — see the cardinality resolution below) — for a SINGLE relation the (subject,relation) is the slot whose `object` changes over time (e.g. `("owner","lives_in")` updates from "London" to "Paris"). The M0-d `Fact.fact_id` is the **version-row id** (one per inserted row); `fact_key` is the **logical-fact id**. M4-a adds `fact_key` to the row; the M0-d `Fact` dataclass carries `fact_id` (version id) — `fact_key` is an internal column exposed via the repository, not added to the frozen `Fact` (no M0-d edit). → impact: Caution. Resolved per ADR-004 cardinality refinement (Option 2): keying is cardinality-aware via a `relation → SINGLE|MULTI` registry (Task 2a). SINGLE: `fact_key = sha256(person_id, subject, relation)`; MULTI: `fact_key = sha256(person_id, subject, relation, object)`. Registry default = MULTI (fail-safe: never overwrite). Table shape unchanged; `compute_fact_key` inputs + the partial-unique invariant both consult the registry.
- **Episodic vs semantic are two loosely-coupled tables in the same keyed DB**, NOT one engine (per the brief). Episodic = an append-mostly event log of raw turns/observations with bitemporal columns (the source history corrections don't destroy). Semantic = the (subject,relation,object) fact-version table with sqlite-vec + FTS5 (what recall/inject query). A semantic fact row carries `source_turn_id` (provenance → an episodic row). M4-a builds BOTH tables + the repository for the semantic store's bitemporal ops; the episodic store gets its table + a thin append/read helper (it is bitemporal but append-mostly — corrections are new rows, never UPDATEs in M4). → impact: Stop (two tables, not one; provenance link exists).
- **Idempotent re-ingest:** inserting the *same* fact-version (same `fact_key` + same `object` + same `valid_from`, with the current row already equal) is a NO-OP (no new row, no interval churn). This is an ADR-required mitigation tested in the golden suite. → impact: Stop.
- Off-hardware: the keyed SQLCipher open + sqlite-vec load may not be installable in CI (same constraint M2-c/M3-a hit). The schema/repository logic is testable against a **real keyed SQLCipher+sqlite-vec DB when the binding installs**, else the golden tests run against a **plain-sqlite fallback connection that loads sqlite-vec without encryption** (the bitemporal SQL is identical; only the `PRAGMA key` differs). The real keyed-open + cipher_memory_security + sqlite-vec-under-SQLCipher round-trip is the **GATED Task 1**. → impact: Caution (the bitemporal correctness is proven off-hardware on the fallback; only the encryption layer is gated).

Simplicity check: considered storing memory in the M3 LanceDB volume — rejected: ADR-004 locks memory in per-person SQLCipher+sqlite-vec (LanceDB has no encryption at rest; memory is the most sensitive store). Considered NULL for open intervals — rejected: a sentinel max-timestamp keeps every range predicate and the partial-unique "one current row per key" index trivial and index-friendly (the ADR-named correctness trap). Considered one merged episodic+semantic table — rejected: the brief locks two loosely-coupled stores. This is the minimum substrate that the M4-b write-path and M4-c recall can sit on.

## Prerequisites
- Specs that must be complete first: **M0-a** (config/paths/mypy), **M0-d** (`MemoryStore`/`Fact`/`PersonId`/`Scope`/`AsOf`/`Vector`/`EmbeddingModel` ports), **M2-b** (`ScopedStore`/`ScopedConnection`/`KeyProvider`/`SecretKey`/`ScopeLockedError`/`CrossScopeError`), **M2-c** (`sqlcipher_open` raw-hex keyed open + `cipher_memory_security`).
- Environment setup required: `sqlite-vec` (the loadable extension — added via `uv add sqlite-vec`, which ships the compiled extension + a `sqlite_vec.loadable_path()` helper) + the M2-c SQLCipher binding (`apsw` + `apsw-sqlite3mc`, or `sqlcipher3-binary` per the Task-1 decision). Off-hardware the golden tests run against a real keyed DB **if** the binding installs, else a plain-sqlite + sqlite-vec fallback; **the real keyed SQLCipher + cipher_memory_security + sqlite-vec-under-SQLCipher round-trip is GATED on-hardware (Task 1).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/memory/__init__.py | create | memory package marker + re-exports |
| /Users/artemis-build/artemis/src/artemis/memory/schema.py | create | the DDL for the two stores + meta table + sqlite-vec virtual table + FTS5 + the partial-unique "one current row per key" indexes + the relation_cardinality registry table (seed SINGLE) + the A-MEM keywords/contextual_description/linked_ids columns on facts; `SENTINEL_TS`; `create_schema(conn, embedder_model_id, dimension)` |
| /Users/artemis-build/artemis/src/artemis/memory/engine.py | create | `open_memory_db(scoped_conn, key, *, embedder_model_id, dimension)` → a keyed, sqlite-vec-loaded connection (via M2-c `sqlcipher_open` + `load_sqlite_vec`); `load_sqlite_vec(conn)`; `DimensionMismatchError`; dimension/meta verification on open |
| /Users/artemis-build/artemis/src/artemis/memory/repository.py | create | `BitemporalRepository`: `add`, `update` (close interval + insert), `tombstone` (DELETE), `as_of` query, `history(fact_key)`, episodic `append_episode`/`read_episodes`; the half-open interval + sentinel logic; idempotent re-ingest; bump_access, purge (only hard-delete), compute_fact_key/cardinality_of/set_cardinality (cardinality-aware keying) |
| /Users/artemis-build/artemis/src/artemis/memory/store.py | create | `SqliteMemoryStore` — the partial `MemoryStore` adapter skeleton wiring the port to the repository (`add_fact`, `recall` (no-rank passthrough in M4-a), `update_fact`, `delete_fact`); `inject_context` raises `NotImplementedError` (filled by M4-c) |
| /Users/artemis-build/artemis/tests/test_memory_bitemporal.py | create | the golden tests: as_of histories, idempotent re-ingest, UPDATE-closes-prior-interval, never-hard-delete, dimension-lock, two-store provenance link, wall |

## Tasks
- [ ] Task 1 (GATED — on-hardware, the ADR-004 build-time spike): Prove sqlite-vec under SQLCipher end-to-end + decide the binding — files: `/Users/artemis-build/artemis/src/artemis/memory/engine.py` — on the Mini with the M2-c SQLCipher binding installed + `sqlite-vec`: (a) confirm the chosen binding (APSW+sqlite3mc per ADR-004, else sqlcipher3) and finalise the two extension-load calls in `load_sqlite_vec(conn)`; (b) open a keyed SQLCipher DB via M2-c `sqlcipher_open`, `load_sqlite_vec(conn)` succeeds on the keyed connection, create a `vec0` virtual table, insert + KNN-search a vector, and confirm `PRAGMA cipher_memory_security` is ON and the file is unreadable with the wrong key; (c) record the binding + the exact load API + any version pins in the handoff. → impact: this is the architecturally-sound-but-thinly-documented page-layer-encryption claim from ADR-004 — prove it before the rest of M4 builds on it. — done when: a keyed SQLCipher DB loads sqlite-vec and round-trips a KNN search; wrong key fails; cipher_memory_security ON; recorded in handoff.

- [ ] Task 2: Define the schema DDL for both stores — files: `/Users/artemis-build/artemis/src/artemis/memory/schema.py` (+ `memory/__init__.py`) —
  - module constant `SENTINEL_TS = "9999-12-31T23:59:59Z"` (open-interval upper bound) and `def now_iso() -> str` (UTC ISO-8601, `Z`-suffixed, second precision).
  - `def create_schema(conn, *, embedder_model_id: str, dimension: int) -> None` executing (idempotent — `IF NOT EXISTS`):
    - `meta(key TEXT PRIMARY KEY, value TEXT)` — on first create insert `embedder_model_id`, `dimension`, `schema_version="1"`.
    - **episodic** `episodes(episode_id TEXT PRIMARY KEY, person_id TEXT NOT NULL, turn_id TEXT, role TEXT, text TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT NOT NULL DEFAULT '<SENTINEL>', tx_from TEXT NOT NULL, tx_to TEXT NOT NULL DEFAULT '<SENTINEL>', created_at TEXT NOT NULL)` — the bitemporal raw event log (append-mostly; corrections are new rows).
    - **semantic** `facts(fact_id TEXT PRIMARY KEY, fact_key TEXT NOT NULL, person_id TEXT NOT NULL, subject TEXT NOT NULL, relation TEXT NOT NULL, object TEXT NOT NULL, confidence REAL NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT NOT NULL DEFAULT '<SENTINEL>', tx_from TEXT NOT NULL, tx_to TEXT NOT NULL DEFAULT '<SENTINEL>', source_turn_id TEXT, extracted_at TEXT, extractor_model TEXT, salience REAL NOT NULL DEFAULT 1.0, access_count INTEGER NOT NULL DEFAULT 0, last_access TEXT, keywords TEXT, contextual_description TEXT, linked_ids TEXT)` — the (subject,relation,object) fact-version table with provenance + decay inputs. `source_turn_id` references an `episodes.turn_id` (provenance link; not a hard FK to keep append cheap — document). A-MEM structured-note metadata: keywords (space/JSON list), contextual_description (short prose "why noted"), linked_ids (JSON list of related fact_keys for multi-hop) — ADR-004; all nullable, populated on write by M4-b.
      - **Provenance migration note (ADR-004 Refinements 2026-06-21 + 2026-06-23):** the bare `source_turn_id` column above is the v1 form. The deferred typed-source-ref migration (folded into the ADR-021 / M4-b module-push amendment wave, NOT this spec) replaces it with `source_kind TEXT` (∈ `turn|document|module|derived`) + `source_ref TEXT`, and **reserves** two nullable columns `derivation_method TEXT` + `derivation_confidence REAL` for a future reflection/consolidation loop (rows where `source_kind='derived'` and `source_ref` is a JSON list of parent fact-ids). Nothing in M4-a/M4-b populates `derived`; the columns are additive hooks only. When that migration runs, add the columns here and migrate existing rows to `source_kind='turn'`.
    - **partial-unique index** `idx_facts_one_current` UNIQUE on `(fact_key)` WHERE `tx_to = '<SENTINEL>'` — enforces **at most one currently-believed (tx-open) version per logical fact** (the core bitemporal invariant; a second open row for a key is impossible by construction). Add supporting non-unique indexes on `(person_id, valid_from, valid_to)` and `(person_id, tx_from, tx_to)` and `(fact_key, tx_from)`.
    - **sqlite-vec** virtual table `facts_vec` via `CREATE VIRTUAL TABLE IF NOT EXISTS facts_vec USING vec0(fact_id TEXT PRIMARY KEY, embedding FLOAT[<dimension>], distance_metric=cosine)` — dimension taken from the arg (dimension-lock). **U5 fix:** declare `distance_metric=cosine` so M4-c's composite score `I = α·exp(−λΔt) + β·access + γ·cosine(m,query)` receives a cosine similarity (after `cosine = 1 − distance` conversion per sqlite-vec's convention) rather than an unbounded L2 distance that would silently distort the multiplier clamp band. Confirm `distance_metric=cosine` is supported in the pinned sqlite-vec version at Task 1.
    - **FTS5** virtual table — **B3 fix:** use a PLAIN (non-contentless) FTS5 table: `facts_fts USING fts5(fact_id, text)` (no `content=''`). This stores both columns in the index so (a) `fact_id` is retrievable on query (not just UNINDEXED noise), and (b) `DELETE` works without `contentless_delete=1` (which requires SQLite ≥ 3.43). At per-person scale the storage cost is negligible. `purge` deletes FTS rows by `DELETE FROM facts_fts WHERE fact_id = ?`.
    - **relation-cardinality registry** `relation_cardinality(relation TEXT PRIMARY KEY, cardinality TEXT NOT NULL CHECK(cardinality IN ('SINGLE','MULTI')), source TEXT NOT NULL DEFAULT 'seed')`. Seed SINGLE rows for `lives_in, birthday, name, age, employer, home_address, phone_number, email`; all others default MULTI. `source ∈ 'seed'|'teacher'|'owner'`. Module constants `SEED_SINGLE_RELATIONS: frozenset[str]`, `DEFAULT_CARDINALITY = 'MULTI'`.
    Substitute the real `SENTINEL_TS` and `dimension` values into the DDL strings. — done when: `uv run mypy --strict src` passes; `create_schema` on a fresh in-memory connection (sqlite-vec loaded) creates `meta`/`episodes`/`facts`/`facts_vec`/`facts_fts` + the partial-unique index, verified by querying `sqlite_master`.

- [ ] Task 3: Implement the keyed, sqlite-vec-loaded engine open + dimension-lock — files: `/Users/artemis-build/artemis/src/artemis/memory/engine.py` —
  - `def load_sqlite_vec(conn) -> None`: enable + load the sqlite-vec loadable extension on `conn` using `sqlite_vec.loadable_path()` (the binding-specific API — APSW: `conn.enableloadextension(True); conn.loadextension(path)`; document the sqlcipher3 alternative in a comment per the binding assumption — RESOLVED/GATED Task 1). Disable extension loading again after.
  - `def open_memory_db(db_path: Path, key: SecretKey, *, embedder_model_id: str, dimension: int, create: bool = True) -> Connection`: call M2-c `sqlcipher_open(db_path, key.as_hex())` (raw-hex keyed open + `cipher_memory_security` — inherited, not re-implemented); `load_sqlite_vec(conn)`; if the DB is new and `create`, call `schema.create_schema(conn, embedder_model_id=..., dimension=...)`; ALWAYS then verify the stored `meta.dimension`==`dimension` and `meta.embedder_model_id`==`embedder_model_id`, else raise `DimensionMismatchError` (the re-index-migration guard, mirrors M3-a). Define `DimensionMismatchError(Exception)`.
  - Provide an `open_for_scope(scoped_conn: ScopedConnection, key: SecretKey, *, embedder_model_id, dimension)` thin wrapper that reads the path from the M2-b `ScopedConnection` (so callers go through the scoped handle / wall) — document that the wall (scope↔key match) is enforced by M2-b before this is reached.
  Bind nothing to network. — done when: `uv run mypy --strict src` passes; against a keyed DB (real binding) OR the plain-sqlite fallback, `open_memory_db` creates+verifies the schema and reopening with a mismatched `dimension` raises `DimensionMismatchError`.

- [ ] Task 4: Implement the bitemporal repository — files: `/Users/artemis-build/artemis/src/artemis/memory/repository.py` — define the two frozen return-type dataclasses at module top (consumed by M4-b/M4-c/M4-d-2 with exact named-field access), then `class BitemporalRepository` constructed with `(conn, person_id: PersonId)`.
  - `FactRow` — frozen dataclass mirroring a `facts` row exactly (column order):
    ```python
    @dataclass(frozen=True)
    class FactRow:
        fact_id: str
        fact_key: str
        person_id: str
        subject: str
        relation: str
        object: str
        confidence: float
        valid_from: str
        valid_to: str
        tx_from: str
        tx_to: str
        source_turn_id: str | None
        extracted_at: str | None
        extractor_model: str | None
        salience: float
        access_count: int
        last_access: str | None
        keywords: str | None
        contextual_description: str | None
        linked_ids: str | None
        subject_entity_id: str | None = None  # added by M4-d-2's facts-column migration; default None pre-migration
    ```
  - `EpisodeRow` — frozen dataclass mirroring an `episodes` row exactly (column order):
    ```python
    @dataclass(frozen=True)
    class EpisodeRow:
        episode_id: str
        person_id: str
        turn_id: str | None
        role: str | None
        text: str
        valid_from: str
        valid_to: str
        tx_from: str
        tx_to: str
        created_at: str
    ```
  Methods (all timestamps default to `now_iso()`; all writes in a single transaction):
  - `def compute_fact_key(self, subject: str, relation: str, object_: str) -> str`: cardinality-aware logical-fact id — looks up `cardinality_of(relation)`; exact serialization (golden-test-asserted, must be stable): join the parts with the `\x1f` unit separator, UTF-8 encode, sha256 hex. SINGLE → `sha256("\x1f".join([self.person_id, subject, relation]).encode()).hexdigest()` (object excluded); MULTI → `sha256("\x1f".join([self.person_id, subject, relation, object_]).encode()).hexdigest()`.
  - `def cardinality_of(self, relation: str) -> str`: returns `SINGLE`|`MULTI`; an unknown relation → insert `DEFAULT_CARDINALITY` and return it.
  - `def set_cardinality(self, relation: str, cardinality: str, *, source: str) -> None`: UPSERT into `relation_cardinality`.
  - `def add(self, subject, relation, object_, confidence, embedding: Vector, *, valid_from=None, source_turn_id=None, extractor_model=None, keywords: tuple[str, ...] = (), contextual_description: str | None = None, linked_ids: tuple[str, ...] = ()) -> str` (returns the new `fact_id`; the A-MEM `keywords`/`contextual_description`/`linked_ids` kwargs are written to the new facts columns — M4-b populates them, default empty): compute `fact_key = compute_fact_key(subject, relation, object_)` (cardinality-aware: MULTI → a different object yields a different key so values coexist; SINGLE → object excluded so a changed object maps to the same key → idempotency/UPDATE); **idempotency guard** — if the current (tx-open) row for `fact_key` exists AND has the same `object_` AND its `valid_from` ≤ the requested `valid_from`, return that existing `fact_id` and write NOTHING (NO-OP re-ingest); else if a *different* current object exists for the key — **F3 fix:** raise `CurrentFactConflict(fact_key)` (define `class CurrentFactConflict(Exception)` in `repository.py`; this is a safety contract on the primitive, not a retry — M4-b's decider routes a SINGLE-cardinality update to `update()`, so this case means a bug in the caller); else insert a new version row with `valid_from`(or now), `valid_to=SENTINEL`, `tx_from=now`, `tx_to=SENTINEL`, a fresh `fact_id` (uuid4); insert the embedding into `facts_vec(fact_id, embedding)` (assert `len(embedding)==dimension` else `DimensionMismatchError`); insert the `subject relation object` blob into `facts_fts`. (Document: `add` is the A path; `update` is the U path of M4-b; `CurrentFactConflict` fires only if the caller mis-routes — M4-b's decider never calls `add` when a different current SINGLE-cardinality object already exists.)
  - `def update(self, fact_key, new_object, new_confidence, embedding, *, valid_from=None, source_turn_id=None, extractor_model=None, keywords: tuple[str, ...] = (), contextual_description: str | None = None, linked_ids: tuple[str, ...] = ()) -> str` (the A-MEM kwargs write the new version's facts columns; M4-b populates them): the **U** path — in ONE transaction: (1) find the current (tx-open) row for `fact_key`; (2) **close its tx interval**: set `tx_to = now` on that row (it stays in history — never deleted); (3) insert a NEW version row for the same `fact_key` with `new_object`, `valid_from`(or now), `valid_to=SENTINEL`, `tx_from=now`, `tx_to=SENTINEL`; (4) add its vector + FTS rows. Return the new `fact_id`. (This is "close interval + insert" — the ADR-004 UPDATE semantics; the partial-unique index guarantees the closed row + the new row never both stay tx-open.) `update` is meaningful only for SINGLE-cardinality relations; MULTI supersession = tombstone+add (decided by M4-b), never an in-place object replace.
  - `def tombstone(self, fact_key, *, valid_from=None) -> None`: the **D** path — **F2 fix (single representation, no either/or):** close the current row's tx interval (`tx_to=now`) AND insert a NEW tombstone version row with the same `object`, `confidence=0.0`, `valid_to = valid_from or now_iso()` (closing the valid interval so `as_of(now)` returns nothing for the key), `tx_from=now`, `tx_to=SENTINEL`. This representation was already the drafted default; the "OR `is_tombstone` marker" option is deleted. **Never hard-delete.** The prior history is intact (the closed prior row remains); `as_of(now)` finds no open valid row; `history(fact_key)` shows all rows including the tombstone. `confidence=0.0` on the tombstone row is correct and intentional. — done when below.
  - `def as_of(self, valid_t: str | None = None, tx_t: str | None = None, *, fact_keys: Sequence[str] | None = None) -> list[FactRow]`: return the at-most-one current row per `fact_key` matching `valid_from <= valid_t < valid_to AND tx_from <= tx_t < tx_to` (defaults now); optionally filtered to `fact_keys`. Returns `FactRow` instances (the frozen dataclass defined at module top).
  - `def history(self, fact_key) -> list[FactRow]`: ALL version rows for a key ordered by `tx_from` (for the golden as_of/history assertions + the M4-c owner view).
  - `def semantic_candidates(self, query_embedding: Vector, k: int, *, as_of_tx: str | None = None) -> list[tuple[str, float]]`: a sqlite-vec KNN over `facts_vec` restricted (joined) to currently tx-open + valid rows, returning `(fact_id, distance)` — the top-k seam M4-b/M4-c consume (M4-a only needs it to round-trip; ranking is M4-c). <!-- LINT-DEFER 2026-06-11: KNN vec0 MATCH + bitemporal join SQL skeleton not inlined (WARN M4-a:77); authoring the exact vec0/join SQL is a design choice, not a mechanical fix -->
  - `def get_fact(self, fact_id: str) -> FactRow`: **F4 fix** — look up a single fact-version row by its `fact_id` (the version-row primary key); raise `KeyError(fact_id)` if not found. Used by M4-b Task 3b/3d to resolve `fact_id → fact_key` for UPDATE/DELETE apply steps; used by M4-a's own `update_fact`/`delete_fact` store methods; used by M4-d-2 `_bound_resolve_entity`. No bitemporal filtering — returns whichever version row has this exact `fact_id`.
  - `def bump_access(self, fact_id) -> None`: increment `access_count`, set `last_access=now`; M4-c CALLS it.
  - `def purge(self, fact_key) -> int`: the ONLY hard-delete primitive — permanently DELETE all version rows for `fact_key` + matching `facts_vec`/`facts_fts`; returns rows removed; irreversible, owner-only; every other "delete" is tombstone. M4-c CALLS it.
  - episodic: `def append_episode(self, text, *, turn_id=None, role=None, valid_from=None) -> str` (insert one `episodes` row, returns `episode_id`); `def read_episodes(self, *, as_of_tx=None, limit=50) -> list[EpisodeRow]`.
  All SQL parameterised (no string interpolation of values). — done when: `uv run mypy --strict src` passes; the golden tests (Task 6) exercise every method.

- [ ] Task 5: Implement the partial `MemoryStore` adapter skeleton — files: `/Users/artemis-build/artemis/src/artemis/memory/store.py` (+ re-export from `memory/__init__.py`) — `class SqliteMemoryStore` structurally satisfying `artemis.ports.MemoryStore`, constructed with `(scoped_conn: ScopedConnection, key_provider: KeyProvider, scope: Scope, embedder: EmbeddingModel)`. It lazily opens the keyed DB (via `engine.open_for_scope`, fetching the DEK through `key_provider.dek_for_scope(scope)` — propagating `ScopeLockedError` as the wall: no key → no memory) and builds a `BitemporalRepository(conn, OWNER_PERSON_ID-or-scope-person)`. **F11 fix:** expose `@property def repository(self) -> BitemporalRepository` (returns the lazily-opened repo, forcing the open on first access) and `@property def conn(self)` (the raw connection) and `@property def person_id(self) -> PersonId` — these three public accessors let M4-b's `build_write_path` and M4-d-2's `_bound_resolve_entity` retrieve the repo/conn/person_id without inventing ad-hoc access paths. Implement:
  - `async def add_fact(person_id, fact)` (ASYNC per M0-d MemoryStore port — embeds): the fact triple is STORED text → embed via `(await embedder.embed_documents([f"{fact.subject} {fact.relation} {fact.object}"]))[0]` (M0-d split port: documents/facts get NO query prefix; batch list in, list out), call `repo.add(...)` with the fact fields + provenance (`source_turn_id` from the fact if present). The `repo.add(...)` call stays SYNC (local keyed-DB write — NOT awaited). (Decisioning is M4-b; this is the raw insert path.)
  - `async def recall(person_id, query, k=10, as_of=None)` (ASYNC per M0-d port — embeds): the query is SEARCH text → `qv = await embedder.embed_query(query)` (M0-d split port: single string in, single `Vector` out, async; the adapter applies the query instruction prefix), `repo.semantic_candidates(qv, k, as_of_tx=as_of.tx_at)` (SYNC local DB — not awaited), materialise the `FactRow`s into M0-d `Fact`s, return them (NO decay ranking yet — M4-c overrides/extends this; document the passthrough).
  - `async def update_fact(person_id, fact_id, fact)` (ASYNC per M0-d port — embeds): resolve the row's `fact_key` from `fact_id` (`repo.get_fact` SYNC), embed the new STORED triple via `await embedder.embed_documents([f"{fact.subject} {fact.relation} {fact.object}"])` (documents → NO query prefix), call `repo.update(fact_key, ...)` (SYNC local DB — not awaited).
  - `def delete_fact(person_id, fact_id)` (STAYS SYNC per M0-d port — no embed): resolve `fact_key`, call `repo.tombstone(fact_key)` (tombstone, NEVER hard-delete — doc'd). No `await` anywhere.
  - `async def inject_context(person_id, token_budget, as_of=None)` (ASYNC per M0-d port): `raise NotImplementedError("auto-inject ranking is implemented in M4-c")` (the seam M4-c fills — M4-c's impl awaits `embed`).
  A static `_check: MemoryStore = SqliteMemoryStore(...)` is asserted in the test. — done when: `uv run mypy --strict src` passes; `SqliteMemoryStore` type-checks as a `MemoryStore`; `inject_context` raises `NotImplementedError`; the other four methods round-trip through the repository (Task 6).

- [ ] Task 6: Write the golden tests (the ADR-required mitigation) — files: `/Users/artemis-build/artemis/tests/test_memory_bitemporal.py` — typed pytest. A module fixture opens a memory DB: try the real keyed `open_memory_db` against a `tmp_path` SQLCipher file with a fixed 32-byte test key (`SecretKey`) + a `FakeEmbedder` implementing BOTH `async def embed_documents(self, texts: Sequence[str]) -> list[Vector]` and `async def embed_query(self, query: str) -> Vector` (deterministic fixed-`dimension` vectors, same mapping so a recall query lands nearest its fact — async to satisfy the M0-d split `EmbeddingModel` port). Tests that call the ASYNC store methods (`recall`, `add_fact`, `update_fact`, `inject_context`) are `async def` test functions (`@pytest.mark.asyncio` — establish this convention here; the project gains its first async memory tests) and `await` those calls; tests that exercise the SYNC repository primitives (`repo.add`/`update`/`tombstone`/`as_of`/`history`/`bump_access`/`purge`) stay sync. `delete_fact` stays sync (no await). If the SQLCipher binding is not importable, FALL BACK to a plain sqlite connection with sqlite-vec loaded (same DDL, no `PRAGMA key`) and mark the encryption-specific assertions skipped. <!-- LINT 2026-06-12: async-port cascade — store methods that embed are async; FakeEmbedder.embed_documents/embed_query are async; recall/add_fact tests are async; pytest-asyncio added to test deps if not present. --> Tests:
  - **as_of history (bitemporal):** add `("owner","lives_in","London")` at `valid_from=t1`; `update` the key to `"Paris"` at `tx=t2`; assert `as_of(tx_t=t1)` returns object `"London"` (what we believed at t1) and `as_of(tx_t=t2_or_now)` returns `"Paris"`; assert `history(fact_key)` has exactly 2 rows and the London row's `tx_to == t2-ish` (interval CLOSED), the Paris row's `tx_to == SENTINEL` (open); assert SINGLE keying (`cardinality_of("lives_in") == "SINGLE"`, object excluded from the key).
  - **UPDATE closes prior interval (the trap):** after the update, assert the partial-unique index holds — exactly ONE row for the key has `tx_to == SENTINEL`; attempting to manually insert a second tx-open row for the key raises an IntegrityError (the index is the guard).
  - **idempotent re-ingest (MULTI coexistence):** calling `add` twice with the SAME `("owner","likes","tea")`+same `valid_from` results in exactly ONE row (the second is a NO-OP, same `fact_id` returned); the `facts_vec`/`facts_fts` row count is also 1. Then `add("owner","likes","coffee")` COEXISTS as a second row (MULTI → different object → different key); assert `cardinality_of("likes") == "MULTI"` and both likes rows are current.
  - **cardinality registry:** seed relations resolve SINGLE (`cardinality_of("birthday")=="SINGLE"`); an unseen relation defaults MULTI and persists; `set_cardinality("nickname","SINGLE",source="owner")` overrides + persists; `compute_fact_key` for a SINGLE relation excludes `object` while a MULTI relation includes it (different objects → different keys).
  - **never-hard-delete:** `tombstone(fact_key)` → `as_of(now)` returns NOTHING for the key, BUT `history(fact_key)` still contains the pre-tombstone row(s) (history preserved; demote-not-destroy).
  - **dimension-lock:** reopening `open_memory_db` with a different `dimension` raises `DimensionMismatchError`; inserting a wrong-length embedding raises `DimensionMismatchError`.
  - **two-store provenance:** `append_episode(text, turn_id="T1")` then `add(..., source_turn_id="T1")`; assert the fact row's `source_turn_id` resolves to the episode's `turn_id`.
  - **recall round-trip:** `await store.recall(person_id, "where do I live")` (ASYNC store method) after the update returns the `"Paris"` fact (sqlite-vec KNN over current rows; FakeEmbedder makes the query nearest the lives_in fact).
  - **bump_access (F5 fix):** call `repo.bump_access(fact_id)` on the Paris fact; assert the row's `access_count` incremented by 1 and `last_access` is updated (re-read via `as_of`).
  - **purge (F5 fix):** call `repo.purge(fact_key)` on the lives_in fact; assert the return value > 0 (rows removed); assert `as_of(now)` returns nothing for the key; assert `history(fact_key)` returns an empty list (ALL version rows gone — hard delete confirmed); assert `facts_vec` has no row for any of the removed `fact_id`s; assert `facts_fts` likewise (run `SELECT count(*) FROM facts_fts WHERE fact_id = ?` for each removed id).
  - **port conformance:** `_check: MemoryStore = SqliteMemoryStore(...)` type-checks under mypy.
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_memory_bitemporal.py` passes (encryption-only assertions skip cleanly if the binding is absent).

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/memory/__init__.py, /Users/artemis-build/artemis/src/artemis/memory/schema.py, /Users/artemis-build/artemis/src/artemis/memory/engine.py, /Users/artemis-build/artemis/src/artemis/memory/repository.py, /Users/artemis-build/artemis/src/artemis/memory/store.py, /Users/artemis-build/artemis/tests/test_memory_bitemporal.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add "sqlite-vec==<pinned-pre-v1-version>"` (pin per ADR-004 — pre-v1 API instability) | The sqlite-vec loadable extension (ships compiled + `loadable_path()`) |
| `uv add apsw apsw-sqlite3mc` (or `sqlcipher3-binary` per Task 1) | SQLCipher binding (final choice = Task 1) |
| `uv run mypy --strict src tests/test_memory_bitemporal.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (real keyed DB or plain-sqlite+sqlite-vec fallback) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/memory/**, tests/test_memory_bitemporal.py, pyproject.toml, uv.lock |
| `git commit` | "feat: M4-a two-store memory schema (bitemporal episodic + semantic) on SQLCipher+sqlite-vec + bitemporal repository + golden tests" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (paths, embedder role). NB: embedding dimension is NOT a Settings field — it is read from `EmbeddingModel.dimension` (M0-d) and locked in store metadata (the `meta` table). |

### Network
| Action | Purpose |
|--------|---------|
| `uv add sqlite-vec apsw apsw-sqlite3mc` | Package install (PyPI) |

## Specialist Context
### Security
The memory DB is the owner's **most sensitive store** — born encrypted inside the per-scope SQLCipher vault, opened only via the M2-c raw-hex keyed open with `cipher_memory_security` (no plaintext memory file ever exists). Per-person partition = one keyed file per scope (cryptographic, not logical): a guest scope cannot open the owner file (no DEK → `ScopeLockedError`). M4-a never re-implements the wall or the key handling — it consumes the M2-b/M2-c seam. sqlite-vec runs on transparently-decrypted pages in-process (ADR-004) — the vectors are encrypted at rest. **never-hard-delete** is structural (tombstone + history-preserved), so owner data cannot be silently destroyed by a write-path bug. [FLAG for apex-security (M4 gate): confirm the keyed-open + cipher_memory_security + sqlite-vec-under-SQLCipher properties at Task 1; confirm no fact `object`/episode `text` plaintext is logged.]

### Performance
Per-person memory scale is thousands–tens-of-thousands of facts (ADR-004) — sqlite-vec brute-force KNN is fine; the partial-unique + range indexes keep `as_of` current-row lookups index-driven (the sentinel-not-NULL choice keeps them sargable). Writes are batched in one transaction per op. Decay-driven ranking is M4-c, not here.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/memory/*.py | Type + docstring all exports; document the 4-timestamp half-open + sentinel convention, the partial-unique "one current row per key" invariant, fact_key vs fact_id, the two-store provenance link, dimension-lock, never-hard-delete |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_memory_bitemporal.py` → verify: exit 0 (incl. the `MemoryStore` structural assertion).
- [ ] Run `uv run pytest -q tests/test_memory_bitemporal.py` → verify: as_of history (London@t1 vs Paris@t2), UPDATE-closes-interval (one tx-open row; second open row → IntegrityError), idempotent re-ingest (one row), never-hard-delete (history survives tombstone), dimension-lock raises, two-store provenance link, recall round-trip, cardinality registry (SINGLE vs MULTI keying), bump_access (access_count incremented + last_access updated — F5 fix), purge (ALL version rows + vec + fts removed — F5 fix), `CurrentFactConflict` raised when a SINGLE-cardinality add conflicts with a different current object (F3 fix) all pass.
- [ ] Run `uv run python -c "from artemis.memory import SqliteMemoryStore; from artemis.ports import MemoryStore; print(hasattr(SqliteMemoryStore,'recall') and hasattr(SqliteMemoryStore,'inject_context'))"` → verify: prints `True`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Task 1: keyed SQLCipher DB loads sqlite-vec, KNN round-trips, wrong key fails, `cipher_memory_security` ON; binding + load API recorded → verify in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
