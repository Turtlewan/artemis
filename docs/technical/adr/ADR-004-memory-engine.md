# ADR-004 — Owner-memory engine: custom bitemporal store on SQLCipher + sqlite-vec

**Status:** Accepted (SP0 phase 6, preference-fork resolution + memory deep-dive, 2026-06-04)
**Builds on / resolves:** ADR-001 (stack — SQLite/SQLCipher, LanceDB, MLX) · brain.md § Memory (left "Graphiti-on-Kuzu vs Mem0 OSS as the memory primary" as an open owner-judgment fork). This ADR **resolves that fork**. Research basis: `docs/research/memory-engine-research.md`.

## Context
Artemis needs a **memory of the owner** (episodic + semantic facts about the person), distinct from the document RAG corpus. It must back a `MemoryStore` port with: **per-person hard partition**, **bitemporal** recall (`as_of` — valid-time vs ingest-time), **fact extraction with conflict resolution** (ADD/UPDATE/DELETE/NOOP), **forgetting/decay**, **provenance + owner view/edit/delete**, **auto-injection of structured facts each turn**, semantic recall.

A **LOCKED security invariant** (brain.md § Security / M2) governs this: each scope's data is encrypted with a key only that person can unlock (Secure Enclave/Keychain) — a guest session physically lacks the owner's key. **Whole-disk FileVault does NOT satisfy this** (it unlocks once at boot; zero owner↔guest separation).

A two-round deep-dive (Mem0 vs Graphiti, then custom-feasibility + widened alternatives + Graphiti-workaround viability) produced the decisive findings:
1. **LanceDB OSS has no encryption at rest** (Enterprise/cloud-KMS only) — so it **cannot hold the owner's sensitive memory** under the locked rule. Memory vectors must live inside the encrypted store.
2. **Mem0 OSS** has had its key features (bitemporal, decay, queryable graph) **removed/SaaS-gated** — the free engine misses most of what Artemis needs.
3. **Graphiti** is the best out-of-box capability match (native bitemporal + conflict resolution) but needs a **separate graph DB server** (FalkorDB/Neo4j; embedded Kuzu abandoned by Apple), a **per-person encrypted-volume workaround** for the wall, and a **heavier ~32B model** for reliable extraction — against Artemis's minimal-moving-parts + small-local-model + encryption priorities.
4. A **custom store** can put both the facts and the vector index inside **one per-person SQLCipher file** (via **sqlite-vec**, a loadable extension that operates on transparently-decrypted pages in-process), natively honouring the crypto wall.

## Decision
Build a **custom bitemporal `MemoryStore`** on a **per-person SQLCipher database file + sqlite-vec**, behind the `MemoryStore` port (`person_id` + `as_of` in signatures).

| Aspect | Decision |
|--------|----------|
| **Per-person partition** | **One SQLCipher file per scope**, keyed from Secure Enclave/Keychain (`PRAGMA key`). Cryptographic isolation — a guest can't open the owner's file. Stronger than logical/row tenancy. |
| **Encryption** | **SQLCipher (AES-256) for the whole memory file**, vectors included. **LanceDB is NOT used for memory** (can't encrypt at rest) — LanceDB stays for the document RAG corpus only. |
| **Semantic recall** | **sqlite-vec inside the SQLCipher file** (+ FTS5 for hybrid keyword+vector). Brute-force KNN is fine at per-person memory scale (thousands–tens-of-thousands of facts). |
| **Bitemporal** | Four-timestamp pattern (`valid_from/valid_to`, `tx_from/tx_to`); non-destructive updates (close old interval, insert new); `as_of(valid_t, tx_t)` = WHERE filter. |
| **Conflict resolution** | Copy **Mem0's algorithm**: extract atomic facts → top-k semantic search of existing → LLM emits **ADD/UPDATE/DELETE/NOOP** per fact (UPDATE = close interval + insert; DELETE = soft/tombstone; never destroy). **Decision grammar-enforced via constrained decoding** (fixes small-model JSON-format risk). |
| **Extraction model** | Local teacher (per the sensitivity router); **constrained decoding** for all structured output. |
| **Forgetting/decay** | Score `recency × salience × access` (Ebbinghaus-style); **never hard-delete** — demote below the inject threshold / tombstone via `valid_to`. Owner-driven true purge is a separate explicit action. |
| **Auto-inject** | Each turn, query current (`as_of=now`) facts above the inject threshold, rank, pack into the system prompt within a token budget. |
| **Provenance + owner control** | Each fact carries a **typed source reference** (`source_kind` ∈ turn\|document\|module\|**derived** + `source_ref`), `extracted_at`, `extractor_model`, `confidence` (see Refinements 2026-06-21 + 2026-06-23); owner edit = a normal bitemporal UPDATE (auditable); owner delete = tombstone (or explicit purge). |
| **Upgradeability** | All behind the `MemoryStore` port → Graphiti / memori swappable later if requirements outgrow the custom store. |

### Refinement (2026-06-04, M4 review) — fact identity & cardinality
A "logical fact" is keyed **cardinality-aware** (resolves the multi-valued-relation data-loss bug): a `relation → SINGLE | MULTI` registry — seeded with common relations, **default MULTI (fail-safe: never overwrite)**, one-shot local-teacher classification on first sighting (cached as a rule), owner-overridable. **SINGLE** relations (e.g. `lives_in`, `birthday`) key on `(subject, relation)` with the index-enforced one-current-row invariant (UPDATE = close-interval + insert). **MULTI** relations (e.g. `likes`, `knows`, `owns`) key on `(subject, relation, object)` so values coexist; a superseding change = invalidate-old + add-new. The A.U.D.N. decider respects cardinality. (Apply to M4-a schema/keying + M4-b decider at finalization.)

### Refinement (2026-06-21, cross-store provenance) — typed source reference
Resolves the open question "does a document-sourced fact point back to its source chunk, or bottom out at a
conversational turn?" (status.md; surfaced by reaction E5). **Decision: generalize fact provenance from the
turn-only `source_turn_id` to a typed logical source reference** — `source_kind ∈ {turn, document, module}`
+ `source_ref` (the id within that source: an `episodes.turn_id`, an M3 knowledge **chunk_id** (doc-level
fallback if chunk ids aren't stable), or a module record id e.g. a Finance `txn_id`). One provenance axis,
polymorphic by kind. **Cross-store refs (document/module) resolve tool-mediated — never a cross-store DB
join** (ADR-013 D2: a `document` ref resolves via the knowledge module's get-chunk tool, a `module` ref via
that module's tool), preserving the M2 scope wall. This serves **every** module→Memory push (the audit's
X-cut #3), not only documents, and gives the owner a real "says who? → here is the exact source" trail for
non-conversational facts. **Applied as part of the M4-b module-push amendment that ADR-021 already requires**
(M4-a `facts` schema: replace bare `source_turn_id` with `source_kind`/`source_ref`, migrating existing
turn rows to `kind="turn"`; M4-b write path + `MemoryStore.add_fact` carry the typed ref; the owner view in
M4-c-2 renders it). No new build item — it shapes an amendment already on the list. (Apply at M4 finalization /
the ADR-021 amendment wave.)

### Refinement (2026-06-23, architecture-validation reservations) — additive schema/port hooks
Cheap-now/expensive-later hooks surfaced by the architecture-validation research (`docs/research/2026-06-23-architecture-validation/`). All **additive** — reserve the hook now, build the producer later. (Decisions A, B, I of the reservation walk; full log in the 2026-06-23 handoff / status.)
- **A — `derived` provenance (reserve).** Extend the typed source reference above with a fourth kind: `source_kind ∈ {turn, document, module, **derived**}`. For a `derived` fact, `source_ref` is a **list of the parent fact-ids** it was inferred/consolidated from (not a single source row), and two columns are **reserved** (nullable, unpopulated in v1): `derivation_method` (e.g. `"reflection"`, `"consolidation"`) and a derivation `confidence`. This is the schema hook for a future reflection/consolidation loop that writes facts *about* facts; nothing produces `derived` rows until that loop is built. (Apply to M4-a `facts` schema alongside the 2026-06-21 typed-ref migration.)
- **B — `MemoryStore` port stays record-type-generic (reserve).** The port MUST NOT hard-code `(subject, relation, object)` as the *only* storable record shape. Action-skills/procedures live in the recipe library, not memory — but keep the port open so a future `procedure` record (steps / preconditions / success-criteria) can be added as a new record type without re-shaping the port. Document the port as "record-type-generic; triple is the v1 record type, not the contract." (Apply to M0-d port + the port docstring.)
- **I — parametric-memory stance (doc line).** Artemis does **no runtime weight-learning**. The sole parametric write-path is the offline Codex-distilled `sensitive_reasoner` (ADR-022); all other learning is non-parametric (the recipe library). New capability comes from recipes, not gradient updates. Recorded here and in `brain.md` so it is never re-litigated as an oversight.

### Refinement (2026-06-08, brain/AI research sweep) — patterns to absorb
Memory deep-dive (`docs/research/2026-06-08-agent-memory.md`) re-confirmed **build-custom** — no framework satisfies SQLCipher-at-rest + bitemporal + small-model robustness + per-person partition together (Graphiti needs ~70B for schema-valid extraction; Mem0 OSS lacks bitemporal + at-rest encryption). Absorb three patterns:
- **Composite forgetting score** `I(m,t)=α·exp(−λΔt)+β·access_count+γ·cosine(m,query)` applied as a **retrieval-time re-rank multiplier** (recently-accessed ×1.5, stale ×0.3) on the **semantic** store — refines the "recency × salience × access" decay above into a *surface-time* score, **not** eager deletion (still never hard-delete). Keep TTL-only on the **episodic** store (noise control). (Apply to M4-c recall ranking.)
- **A-MEM structured note metadata** columns on semantic facts (`keywords`, `contextual_description`, `linked_ids`) → multi-hop recall gains. (Apply to M4-a schema.)
- **Graphiti's four-timestamp bitemporal schema** = reference implementation for the `valid_from/valid_to` + `tx_from/tx_to` invariants already specified above.
- **Pin sqlite-vec** (pre-v1 API instability); brute-force re-confirmed fine at memory scale (~17ms @ 1M×128-dim on M1). (Apply to M0-c / M4 deps.)

## Runner-ups ruled out
- **Mem0 OSS** — bitemporal/decay/graph removed or SaaS-gated; would become a thin extract-and-store layer you rebuild anyway; no SQLCipher path.
- **Graphiti** — best capability, but mandates a separate graph DB, a per-person encrypted-volume encryption workaround, and a ~32B extraction model; more moving parts + operational cost. **Kept as the documented upgrade** if a true temporal *graph* ever becomes essential.
- **memori (GibsonAI)** — best off-the-shelf fit (SQL-native, single encrypted file) **if not building custom** — but lacks bitemporal + decay (bolt-on anyway), so the gap to custom is small. Documented fallback.
- **Letta / cognee / txtai / LlamaIndex-memory** — server-heavy, LanceDB-encryption-gap, or retrieval-only; none cover bitemporal + conflict + decay + per-person SQLCipher together.

## Consequences
- **The crypto wall is honoured natively** for the owner's most sensitive store — no FileVault dependency, no encrypted-volume juggling.
- **Effort is modest (~a few hundred to ~1.5k LOC)** behind the port; 5 of 7 capabilities are low-risk/codegen-friendly.
- **Risk concentrates in two spots:** (1) bitemporal interval invariants (the "80% right, 20% silently wrong" trap) and (2) the small model's merge *judgment* (format is solved by grammar; judgment is not). **Mitigations (required):** golden tests asserting `as_of` histories + idempotent re-ingest + UPDATE-closes-prior-interval; constrained decoding; never-hard-delete; owner-edit human-in-the-loop safety net.
- **Build-time spike (gated first task on M4):** smoke-test **sqlite-vec loaded under APSW-sqlite3mc/SQLCipher** end-to-end (architecturally sound — page-layer encryption is transparent to loadable extensions — but not widely documented; prove it early). Also verify the Secure-Enclave-key → `PRAGMA key` flow.
- **Cross-milestone:** affects **M4** (memory build), **M3** (LanceDB stays for docs; not for memory), **M2** (per-scope SQLCipher keys in Secure Enclave).

## Parked (build-phase)
sqlite-vec×SQLCipher smoke test · Secure-Enclave key→PRAGMA flow · decay half-life tuning (7–30 day range) · extraction-quality eval harness on real episodes · entity resolution ("my boss" → named person) · history-compaction job.
