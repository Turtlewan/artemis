# Sweep 2026-06-10 — M3 knowledge layer + M4 memory engine + M4-d entity backbone

Reviewer scope: M3-a/b/c/d, M4-a/b/c, M4-d-1/d-2 (full read) + ADR-004/007/013 + data-model.md (context).
Checks: executor-readiness (DeepSeek literal execution), cross-spec consistency, technical soundness within the locked stack, security, over-engineering.

Severity counts: **BLOCK 4 · UPGRADE 7 · FLAG 11 · RESEARCH 4**

---

## BLOCK

### B1 — M3-d: no source of `PageImage` exists anywhere in the pipeline
`M3-d-visual-document-understanding.md` — Task 4 (`VisualStage.process(page_images: Sequence[PageImage], ...)`), Task 5 (`VisualIngestPipeline` "overrides ingest to call the visual stage when the parsed document has page images").
M3-a's `RawItem` carries `raw_bytes`/`text`; `ParsedDocument` is `{text, blocks}` and `ParsedBlock` is text+page+bbox — **no field anywhere carries page images**, and no M3-d task adds page-image extraction (e.g. Docling page-image export, or PDF-page rasterisation). A literal executor has no way to construct the `Sequence[PageImage]` that `VisualStage.process` and the Task 7 tests require, and "when the parsed document has page images" is a predicate over a type that cannot have them. **Fix:** amend M3-d (or M3-a) to add an explicit page-image extraction step — e.g. extend `ParsedDocument` with `page_images: Sequence[PageImage]` populated by `DoclingParser` (Docling exposes page images) and by `FakeParser` (synthetic bytes), and have `VisualIngestPipeline` read that field.

### B2 — M3-d: the separate `page_images_{scope}` table is unimplementable with M3-a's `LanceDBVectorStore`
`M3-d-visual-document-understanding.md` — Task 4 ("write them to a SEPARATE per-scope page-image table (`page_images_{scope}`) via the injected store"), Task 7 tests ("a real `LanceDBVectorStore` for the separate page-image table").
M3-a Task 5 hard-codes the table name `f"docs_{scope}"` and a fixed row schema `{id, vector, text, scope, content_hash, source_id, document_id, page, bbox, char_start, char_end}` plus an FTS index on `text`. Page-image rows have none of the text-chunk fields, need a different (multi-vector/patch) shape, and need a different table name — but `src/artemis/adapters/lancedb_store.py` is **not** in M3-d's Files to Change, so the executor cannot parameterise the table name or schema (scope lock blocks the edit). Also, `embed_page` "MAY return multiple vectors per page" but no row-id scheme for patch vectors is given (e.g. `f"{document_id}:p{page}:v{i}"`), and `VectorStore.add` is one-vector-per-id. **Fix:** either add `lancedb_store.py` to M3-d's file list with an explicit `table_name`/schema parameter (or a dedicated `PageImageStore` adapter in M3-d's own files) and specify the patch-vector id scheme.

### B3 — M4-a: contentless FTS5 (`content=''`) breaks `purge` and fact_id mapping
`M4-a-store-schema-bitemporal-repo.md` — Task 2 (`facts_fts USING fts5(fact_id UNINDEXED, text, content='')`), Task 4 (`purge` "DELETE … matching `facts_vec`/`facts_fts`"), Acceptance Criteria ("purge (all rows + vec/fts removed)").
A contentless FTS5 table (a) does not store or return column values — `fact_id UNINDEXED` is not retrievable on query, so rows can't be mapped back to facts; (b) does not support `DELETE` at all unless created with `contentless_delete=1` (SQLite ≥ 3.43). As written, `purge`'s FTS delete fails at runtime and the acceptance criterion is unpassable. **Fix:** amend the DDL to either a plain FTS5 table (store `fact_id` + the text blob — trivial size at per-person scale) or `content='', contentless_delete=1` with an explicit rowid↔fact_id mapping. Given the fact table is small, the plain (non-contentless) table is the simplest correct choice.

### B4 — M4-c: Task 4 requires editing `compose_brain`, which lives in `gateway.py` — not in M4-c's Files to Change
`M4-c-recall-autoinject-decay-owner.md` — Task 4 ("Update `compose_brain` to optionally construct a `SqliteMemoryStore` + `MemoryWriteQueue` … and pass them … to the `Brain`"), Files to Change table.
M1-c Task 1 creates `compose_brain` in `/src/artemis/gateway.py` (verified; M4-d-2's Assumption also states this and depends on M4-c having edited that file). M4-c's Files to Change lists only `decay.py`, `store.py`, `owner.py`, `brain.py`, `__init__.py`, tests — **`gateway.py` is missing**. Under the surgical scope lock, the executor must either skip the compose wiring (leaving M4-d-2's Task 4 with no memory-active branch to hook into) or violate scope. M3-c handled the identical situation with an explicit STOP-and-FLAG escape (M3-c Task 4); M4-c has no such escape. **Fix:** add `/Users/artemis-build/artemis/src/artemis/gateway.py | modify` to M4-c's Files to Change (and the Permissions + git-add tables).

---

## UPGRADE

### U1 — M3-a: add a `sensitivity` column to the LanceDB chunk schema now (dimension-locked table; later change = re-index migration)
`M3-a-ingestion-pipeline.md` Task 5 row schema vs `data-model.md` §2 ("every Chunk … carries scope + **sensitivity**"). The chunk row has `scope` but no `sensitivity`. Sensitivity is derivable from scope *by default*, but data-model locks an explicit per-item `public` override ("owner likes jazz") — that override has no home in the M3-a schema, and the M3-b provenance gate ("no sensitive chunk to cloud") will eventually need it per-chunk. Because the table carries dimension-lock metadata and re-shaping it later is an explicit re-index migration, adding `sensitivity TEXT DEFAULT 'sensitive'` now is one line; retrofitting is a migration. Same applies to M3-d's `page_images_{scope}` table.

### U2 — M4-a/M4-c: `facts_fts` is written but never queried — the ADR-004 "hybrid keyword+vector" recall half is missing
`M4-a` Task 2/Task 4 write `facts_fts` on every add/update; ADR-004 locks "sqlite-vec inside the SQLCipher file (+ FTS5 for **hybrid** keyword+vector)". But no spec ever reads it: `semantic_candidates` is vec-KNN only and M4-c's `recall` upgrade is "semantic_candidates → decay multiplier re-rank". As specced, FTS5 is dead weight (written, indexed, purged — never searched). Either add an FTS leg + simple fusion to M4-c `recall` (one query + RRF over the two id lists — the `rrf.py` helper from M3-b is already in-repo), or drop the FTS table. The former honours the ADR; the latter is the simplicity call — but pick one in the spec.

### U3 — M3-c: static spotlighting delimiters are escapable — sanitise or randomise
`M3-c-agentic-multihop.md` Task 2: `<<RETRIEVED_DOC …>> … <<END_RETRIEVED_DOC>>` is a fixed, guessable delimiter. A document that itself contains `<<END_RETRIEVED_DOC>>` followed by instruction text breaks out of the data block — the classic delimiter-injection bypass. The loop is read-only so blast radius is a degraded answer, but the fix is cheap: strip/escape any occurrence of the delimiter token inside chunk text before wrapping (one `str.replace`), or use a per-call random delimiter suffix. Add to Task 2 + a Task 6 test (chunk containing the literal end-delimiter stays inert).

### U4 — M3-c: `as_agentic_fn` pays for a synthesis LLM call and throws the answer away
`M3-c` Task 1: `as_agentic_fn` returns `self.run(query, scope).chunks[:k]` — `run` always ends with the `_synthesise` responder call, so every `retrieve(mode="agentic")` via M3-b's seam burns a full synthesis completion whose output is discarded. Add a `collect_only: bool = False` param to `run` (skip step 3 when True) and have `as_agentic_fn` pass it. One flag, saves the most expensive call on the chunks-only path.

### U5 — M4-a: declare `distance_metric=cosine` on `facts_vec` (M4-c's `recall_multiplier` consumes a cosine term)
`M4-a` Task 2 declares `vec0(fact_id TEXT PRIMARY KEY, embedding FLOAT[d])` with no distance metric — sqlite-vec defaults to L2. M4-c's composite score `I = α·exp(−λΔt) + β·access + γ·cosine(m,query)` and its clamp band assume a cosine in [−1,1]; feeding an unbounded L2 distance (or an ad-hoc conversion) silently distorts the multiplier. Add `distance_metric=cosine` to the vec0 DDL (supported in pinned sqlite-vec) and state in M4-c Task 2 that `cosine = 1 − distance` (sqlite-vec cosine returns distance, not similarity).

### U6 — M4-d-2: resolving EVERY fact subject to a PERSON entity manufactures spurious person rows
`M4-d-2` Assumption ("every fact subject resolves to a stable PERSON entity") + Task 2. Extraction subjects are not all people — "my car", "the project", a place name, etc. will each get a `person:` entity row + alias, polluting `entities`, `list_entities(PERSON)`, and `resolve_entity` results, and the merge story only covers person identities. Options within scope: (a) only resolve when `ef.subject == "owner"` or the subject matches an existing person alias (resolve-don't-create for unknowns), or (b) keep create-always but document the noise + a cleanup path. The spec currently states the boundary (PERSON-only) but not the noise consequence; option (a) is one condition.

### U7 — M3-a: `WebConnector` has no URL-scheme allowlist
`M3-a` Task 2: `WebConnector.fetch` passes `source.uri` straight to `_fetch_url`/trafilatura. Add an explicit `http`/`https` scheme check (raise `ValueError` otherwise) mirroring the `FileConnector` allowed-roots guard — blocks `file://`/other-scheme retrieval through the web path. One line + one test.

---

## FLAG

### F1 — M3-a: two different path formulas for `volume_vectors_dir`, and `<slot>` has no source
Assumption (line 19): `volume_vectors_dir(settings, scope) -> <volume_root>/<scope>/lancedb`. Task 1: returns `<mounted-volume-root>/<slot>/<scope>/lancedb` — with `<slot>` appearing only in the second formula, no `slot` parameter, and no statement of whether `Settings.volume_root` already contains the slot. The done-when says "returns the documented path" — which one? A literal executor will pick arbitrarily. Pick one formula and state where the slot comes from (e.g. "volume_root is slot-qualified by the env file; the function appends only `<scope>/lancedb`").

### F2 — M4-a: tombstone representation is specified as "X OR Y"
Task 4 `tombstone`: "insert a tombstone version row (… `valid_to = valid_from or now` …) **OR** a dedicated `is_tombstone` marker. Document the chosen…". Specs are execution scripts — an either/or forces DeepSeek to design. The drafting note leans to the valid_to-closing row; delete the "OR is_tombstone marker" clause and make the drafted representation the single instruction (and state `confidence=0.0` is or isn't part of it — currently both appear).

### F3 — M4-a: `add` behaviour undefined when a SINGLE-cardinality key already has a different current object
Task 4 `add`: "If a *different* current object exists for the key, this is NOT add — callers wanting replace use `update`." Not-add is not a behaviour: as written the insert proceeds and hits the partial-unique `IntegrityError`. Specify it: raise a typed error (e.g. `CurrentFactConflict`) or return the existing id without writing. M4-b's decider should route this to UPDATE, but a safety contract on the primitive is still needed (the golden tests can't assert an unspecified outcome).

### F4 — M4-a/M4-b: the fact_id → row/fact_key lookup primitive is consumed three times but never defined
M4-a Task 5 (`update_fact`/`delete_fact`: "resolve the row's `fact_key` from `fact_id`"), M4-b Task 3b (materialise `Candidate`s — "resolve each `fact_id` to its current triple via `repo.as_of`/a lookup") and 3d (resolve `fact_key` from `decision.target_fact_id`). `BitemporalRepository`'s method list has no by-fact_id getter (`as_of` filters by `fact_keys` only). Add `get_fact(fact_id) -> FactRow` to M4-a Task 4's method list so all three call sites have a named primitive.

### F5 — M4-a: Acceptance Criteria require `bump_access` and `purge` tests that Task 6 never specifies
AC bullet 2 ends "…bump_access (access_count/last_access updated), purge (all rows + vec/fts removed) all pass" — but Task 6's golden-test list contains no bump_access or purge test. Add the two test bullets to Task 6 (or the AC is unverifiable as written).

### F6 — M4-d-2: AC contradicts the spec's own error contract ("unknown id → `KeyError`")
Acceptance Criteria line: "…unknown id → `KeyError`" — but Task 3 and Task 5 specify unknown id ⇒ `EntityNotFound("entity not found")` (sanitised, deliberately NOT the raw `KeyError`). Fix the AC bullet to `EntityNotFound`.

### F7 — M3-d: `is_visual(self, item)` — untyped param, and Task 4 calls it with literal `...`
Task 1 Protocol: `def is_visual(self, item) -> bool` — no annotation; `mypy --strict` (the spec's own gate) fails on it. Task 4: "if `visual.is_visual(...)`" — the argument is literally an ellipsis; the executor doesn't know whether to pass the `PageImage`, the `RawItem`, or a mime. Type the param (likely `PageImage | RawItem` or just the mime string) and write the real call.

### F8 — M4-d-1: AC #2's `python -c` against stdlib `sqlite3` cannot pass
The AC runs `create_schema` on a plain `sqlite3.connect(':memory:')` — but M4-a's `create_schema` creates the `vec0` virtual table, which requires sqlite-vec loaded (and stdlib connections need `enable_load_extension` plumbing the command doesn't do). The bullet's own NOTE admits this; make the fixture-based pytest assertion the primary AC and delete the python-c variant (a literal executor treats the first runnable as the gate).

### F9 — M3-a: `VectorStore.search(scope, query, k)` — `query`'s type is unstated
Task 5 names the param `query` and says "LanceDB ANN search on `vector`"; M3-b Task 2's fallback calls `search(scope, query_vector, k*2)`. Presumably a vector, but the M3-a signature never says so. State `query: Sequence[float]` (or whatever M0-d's port declares) in Task 5.

### F10 — M4-c: the `recall_multiplier ≈ 0.3 for a long-stale fact` check is under-determined
Task 1 done-when / Task 5: with `I = α·exp(−λΔt) + β·access_count + γ·cosine` and γ=1, a stale fact with high cosine (≈0.9) scores ≈0.9, not 0.3 — the assertion only holds for a particular cosine input the spec never states. Specify the test inputs (e.g. `cosine=0.1, access_count=0, Δt=180d`) so the clamp assertion is deterministic.

### F11 — M4-a: `SqliteMemoryStore` exposes no named accessor for the repo/conn that `build_write_path` (M4-b) and `_bound_resolve_entity` (M4-d-2) need
M4-b Task 4: "constructs the extractor/decider/write-path from a `SqliteMemoryStore`'s repository + embedder"; M4-d-2 Task 3: "build the `BitemporalRepository` + `EntityRepository` ONCE … from the store's keyed connection + owner `person_id`". M4-a Task 5 defines the store's port methods only — no public `repo`/`conn`/`person_id` attribute is named. Three downstream call sites will each invent an access path. Add to M4-a Task 5: expose `repository` (property, opening lazily) — one line.

### F12 — M3-a: `has_document` is introduced inside Task 6 ("add it") but belongs to the Task 5 adapter
Task 6 step 3 adds `store.has_document(document_id, content_hash)` parenthetically; Task 5's method list (`add`/`search`/`delete_document`) omits it. A wave-parallel executor building Task 5 won't include it. Move it into Task 5's method list.

---

## RESEARCH

### R1 — LanceDB table-metadata mechanism for the dimension-lock
M3-a Task 5: "On first create, write table metadata `{embedder_model_id, dimension}` … on open, ASSERT". LanceDB has no first-class mutable table-metadata API — the options are pyarrow schema metadata at creation, a one-row `_meta` sidecar table, or a JSON file beside the table dir. Confirm the mechanism on the installed LanceDB version before the build (the M4-a equivalent uses an explicit `meta` table — mirroring that with a `_meta` LanceDB table or sidecar JSON is the safest literal instruction). Same mechanism is needed by M3-d's page-image table.

### R2 — mlx-openai-server `/v1/rerank` endpoint existence (already gated — keep)
M3-b Assumption/Task 5 correctly gates this with the chat-completions constrained-decode fallback. Carry as research at bring-up: confirm whether the mid-2026 mlx-openai-server exposes a rerank route for Qwen3-Reranker or whether the chat fallback is primary (affects the `_score` seam's default).

### R3 — PyTorch MPS "2.5.1, NOT 2.6.0" pin currency
M3-d locks ColQwen2.5 Light on "PyTorch MPS 2.5.1 (NOT 2.6.0)" (from ADR-007, 2026-06-08). By mid-2026, 2.5.1 is ~18 months old and several MPS-fix releases past 2.6.0 exist; verify at the Task-6 spike whether the known 2.6.0 MPS regression is fixed in a current release before freezing an old torch into the dependency set (an old pin can conflict with other deps on the same box).

### R4 — sqlite-vec `vec0` TEXT PRIMARY KEY + filtered KNN under the pinned version
M4-a Task 2 declares `vec0(fact_id TEXT PRIMARY KEY, …)` and Task 4's `semantic_candidates` does KNN "restricted (joined) to currently tx-open + valid rows". vec0's support for non-rowid TEXT primary keys and for combining `MATCH … AND k=?` KNN with a post-join filter (over-fetch factor needed so the filter doesn't starve k) is version-sensitive pre-v1. The Task-1 gated spike should explicitly cover: TEXT PK round-trip, the KNN+join pattern, and the over-fetch multiplier — add these three items to Task 1's checklist.

---

## Over-engineering check
No material findings. The specs consistently defer (graph mode stub, ColPali seam-only, no background decay daemon, no retry loops). Two borderline items already noted as upgrades rather than cuts: U2 (FTS5 written-never-read — either use it or cut it) and M3-d's `VisualRetriever` seam (justified by ADR-007's "IN behind the port" lock).

## Cross-spec consistency confirmations (checked, no finding)
- Bitemporal predicate: M4-a `as_of` and M4-d-2 `facts_for_entity` are logically identical (`tx_to > now` ⟺ `now < tx_to`). ✓
- `facts` column list: M4-a DDL ⊂ M4-d-1 amendment (`subject_entity_id` after `linked_ids`) ⊂ M4-d-2 kwargs/FactRow field. ✓
- `MemoryWritePath`/`MemoryWriteQueue`/`build_write_path` signatures: M4-b ↔ M4-c ↔ M4-d-2 quote each other exactly. ✓
- `EntityRepository`/`EntityRow`/`EntityRef`/`person_fact_key`: M4-d-1 exports = M4-d-2 Assumption list = data-model.md §3 Entity/EntityAlias fields. ✓
- `BrainResponse.path` is a plain `str` in M1-b, so M3-c's `path="agentic"` type-checks without an M0-d/M1-b edit. ✓
- `Mode` literal, `agentic_fn` seam signature `(str, Scope, int) -> list[RetrievedChunk]`: M3-b ↔ M3-c match. ✓
- Both M3-c and M4-c modify `brain.py` additively (optional ctor params, distinct branches) — compatible in either build order. ✓
