<!-- aligned 2026-06-11 to ADR-012/013 + contracts.md -->
# Artemis — Conceptual Data Model (SP0 phase 4)

_Status: **SP0 phase-4 conceptual data model** (the ADR-008 early-data case — Artemis is data-heavy, so the
model is drawn before the stack locks). Entities, attributes, relationships, and **scope-partition** — NOT
physical DDL (that's a build-time spec for DeepSeek). Synthesised from the locked decisions in
[`brain.md`](./brain.md) + the decomposition in [`overview.md`](./overview.md). Feeds phase-5 (stack
re-confirm) and phase-6 (the build specs that turn these into real schemas)._

_Reconciled 2026-06-09 (M8 spoke wave): `Skill`→`Recipe` (M7 lifecycle + 3 authors), added `PendingAction`
(ADR-012/GATE), corrected Recipes to owner-private/encrypted, and pointed the opaque-module note at the
per-module design docs. Module internals stay opaque by design (Modeling Decision #1) — not enumerated here._

**Scope of this model:** the **central + cross-cutting** entities the brain depends on — identity/scope,
the knowledge corpus, the two memory stores, the module system, and the cross-cutting tags. **Module-internal
operational data is intentionally opaque here** — each module owns its own schema (internals are free); the
model only fixes the *contract* (what a module exposes via tools + pushes as knowledge).

---

## Two orthogonal classifiers govern every datum
Everything below is tagged on two independent axes — these are the load-bearing concepts:

| Axis | Values | Decides | Enforced by |
|------|--------|---------|-------------|
| **Scope** (WHO) | `owner-private` · `guest:{person_id}` · `general` | who can read it | **crypto wall** — physically separate SQLCipher DB + vector index per scope; key in Secure Enclave, gated to owner biometric (a guest session lacks the key) |
| **Sensitivity** (where it may be processed) | `sensitive` (default for personal sources) · `public` (explicit) | local-only vs cloud-eligible | **sensitivity router** — provenance gate (source-derived) + free-text classifier + **fail-safe→local** |

**Default rule (LOCKED):** sensitivity is **derived from source/scope** — anything in `owner-private` or
carrying PII is `sensitive` (never leaves the box). `public` is an explicit opt-in on the rare owner datum
that is safe for cloud (e.g. "owner likes jazz"). `general`-scope content is `public`. When unsure → `sensitive`.
The two axes are orthogonal but correlated: all `owner-private` defaults to `sensitive`; `guest`/`general`
may be `public`.

---

## Entity families

### 1 · Identity & scope
- **Person** — `person_id` (PK, the hard partition key everywhere) · `role` (`owner` | `guest`) · `display_name`
  · enrolment metadata. Exactly one `owner`; zero-or-more `guest`s. No shared "household" scope (locked).
- **Voiceprint** — `person_id` (FK) · ECAPA-TDNN embedding · enrolment timestamp. Used for speaker-ID →
  identity (NOT auth). Unknown voice → ephemeral `guest` (least-privilege), no Person row until enrolled.
- **Scope (partition)** — `owner-private` · `guest:{person_id}` · `general`. Not a column — a **storage
  partition** (separate encrypted DB + vector index). Every other entity *belongs to exactly one scope*.
- **Permission** — `person_id` × `module_id` → `{none | guest | full}`. Owner = `full` everywhere; guest =
  `guest`-level on the few modules that opt in (per-module manifest detail). Default-deny.

### 2 · Knowledge corpus — the document "second brain" (scope: mostly `owner-private`)
The immutable-corpus RAG store. Distinct entity family from Memory (the two stores are loosely coupled).
- **Source** — a connector or capture origin (a webpage, a video, a scanned doc, a Gmail thread). `source_id` ·
  `type` · `origin_ref` (URL / file / message-id) · ingest metadata.
- **Document** — the normalized unit after ingestion. `document_id` · `source_id` (FK) · `content_hash`
  (idempotency) · `scope` · `sensitivity` · ingest + extractor version. One Source → one-or-more Documents.
- **Chunk** — `chunk_id` · `document_id` (FK) · text · **`embedding`** (vector; dimension locked in store
  metadata) · BM25/FTS terms · **provenance + locator** (page / timestamp / bbox → deep-link back to Source) ·
  `scope` · `sensitivity`. The retrieval unit (hybrid vector + keyword + rerank).
- _Module **knowledge contributions** (§4) also land here as Documents/Chunks with a back-reference to the
  originating module record — this is the "push" half of the hybrid data flow._

### 3 · Memory — Artemis remembering *you* (scope: `owner-private`; tiny `guest` profiles)
Two logical stores, different indexes (locked: NOT one unified engine). `person_id` is a hard partition key
on every node/edge/vector.
- **Episode** (episodic store) — a time-anchored event/interaction. `episode_id` · `person_id` · raw content ·
  **bitemporal stamps** (`event_time` + `ingestion_time`, so corrections never destroy history) · provenance.
  Append-only raw log; never re-fed to the LLM directly — retrieved via distilled tiers.
- **SemanticFact** (semantic store) — a distilled `(subject, relation, object)` triple. `fact_id` · `person_id`
  · subject/relation/object · `confidence` · provenance (links to source Episode/Chunk) · **`valid_at` /
  `invalid_at`** (temporal validity + explicit supersession for stale-confident facts) · embedding + graph edges.
  Written via **A.U.D.N.** (ADD/UPDATE/DELETE/NOOP) to dedupe + resolve contradictions; extraction runs on the **local `sensitive_reasoner`** (Qwen3.6-27B), not the teacher — owner memory content is sensitive and must not reach the cloud (ADR-003).
- **Entity** (cross-module backbone — ADR-013) — a first-class referenced node in the owner-private memory
  DB: `entity_id` (PK, stable) · `entity_type` (`person` | `place` | `goal`) · `canonical_name` · `external_ref`
  (e.g. email; nullable) · `attributes` (deferred-schema JSON, nullable). **Distinct from §1 Person/`person_id`**
  (the scope-partition owner): an Entity is a person/place/goal the owner's facts are *about*. For a `person`
  Entity the `entity_id` is the **`person_fact_key`** — the canonical cross-module person pointer (same email ⇒
  same key) that every spoke references instead of ad-hoc strings. `SemanticFact.subject_entity_id` → Entity
  (soft link, no FK). Place/Goal entities exist now but are created on-demand by their owning spokes
  (Productivity→Goal, Maps/Travel→Place); detailed type schema deferred (ADR-013 Decision 6).
- **EntityAlias** — resolution map ("my wife" → `entity_id`) · normalized/lowercased · `source`
  (`seed`|`extracted`|`owner`). Resolves references to an Entity before retrieval. Cross-module references use
  a logical **`{module, entity_id}`** (EntityRef) resolved via the target module's tool through the
  ToolRegistry — never a cross-store join (ADR-013 Decision 2); `memory.resolve_entity` is the memory-module
  resolver.
- **Distillation tiers** — working / episodic / semantic / procedural are *roles over the above*, not new
  tables: forgetting = recency × salience × access-frequency decay, **distil up to SemanticFact before
  discarding** the raw Episode (no catastrophic forgetting).
- **Guest preference profile** — a *tiny* semantic-only slice: a handful of SemanticFacts in the
  `guest:{person_id}` partition (likes/preferences). No episodic log, no personal stores for guests.

### 4 · Module system (the contract — scope: `general` registry, contributions inherit module scope)
- **Module** — `module_id` · name · group · version. A first-class plugin.
- **Manifest** — `module_id` (FK) · `tools[]` · `data_scope` · owner/guest `permissions` · `proactive_hooks[]`
  · `ui`. **Versioned contract.** Populates the tool registry (indexed for RAG-for-tools).
- **Tool** — `tool_id` · `module_id` · typed input/output schema. The live/exact interface the brain calls
  (typed dispatch; one gated sandboxed code-exec module platform-wide).
- **ProactiveHook** — `module_id` · schedule (interval/cron) · deterministic `check` · `urgency` · `delivery`
  · `dedup_key` · `needs_llm`. Run by the Heartbeat (silent-success).
- **Recipe** — a distilled SKILL.md-shaped automation artifact (frontmatter + instructions + optional signed
  script). **Recipes are data**, loaded at runtime (RAG-for-recipes). `name`/`recipe_id` · description
  (embedded for retrieval) · `action_class` (`read-only`|`no-data`|`touches-data`|`takes-action`) · `status`
  (`CANDIDATE`→`PENDING`→`ENABLED`→`RETIRED`) · body-hash (dedupe) · recurrence-count · provenance · HMAC
  `signature` · `task_class_key`. **Three authors**, all flowing through one owner-gated review (M7-b):
  teacher-escalation distill (M7-a2), the Curiosity loop (M7-c), and owner-behaviour **capture-graduation**
  (M8-d-c2). Promotion = recurrence (N≥2) or owner command; only `read-only`/`no-data` auto-enable, the rest
  are owner-approved. Stored on the **owner-private encrypted volume** (M7-a1), not `general`.
  (Terminology: "recipe", not "skill".)
- **KnowledgeContribution** — the contract for the "push" half of hybrid: `module_id` · originating record ref
  · → emits Document/Chunk(s) into the knowledge corpus with provenance back to the module record.
- **Module operational store** — **OPAQUE.** Each module owns its own schema (the finance transactions table,
  the calendar events table…). The central model does not define these; it only sees them through `Tool`
  (live exact queries) + `KnowledgeContribution` (pushed knowledge). This is the source-of-truth side of the hybrid flow.
  _The first spoke wave realizes this contract concretely — see `docs/technical/modules/{calendar,gmail,productivity}.md`
  for each module's internal stores (Calendar read-cache/overlay/preferences/activity-log · Gmail metadata read-cache ·
  Productivity owned areas/projects/tasks/recurrence/suggestions). They remain opaque to this central model by design._

### 5 · Cross-cutting / operational (lightweight)
- **ProvenanceRef** — a reusable reference (source · locator · timestamp) carried by Chunks, Facts, Episodes
  → deep-link + selective re-embed on extractor upgrade + audit.
- **AuditEntry** — redacted log of tool calls, escalations, cloud-egress decisions, high-stakes confirmations,
  self-confidence (the telemetry the Curiosity-Loop gap-scan + observability need).
- **Notification** — Heartbeat → ntfy delivery record (priority · tags · dedup · action-button state). May be
  treated as operational at build time; listed for completeness.
- **PendingAction** — a one-off external-effect action staged for owner approval — distinct from a Recipe
  (ADR-012; "permission-now" vs the recipe's "automate-later"). `action_id` · `module` · `tool` (fq) · `args`
  (bound payload) · `summary` (plain-language) · `action_class` (`takes-action`) · `status`
  (`PENDING`→`APPROVED`|`REJECTED`|`EXPIRED`) · `created_at` · `expires_at` · `result`. Owner-private
  (SQLCipher). `approve` re-dispatches the bound `Tool` via the registry and executes **once**; expired
  actions never execute. The gate every external-effect spoke write routes through (Calendar attendee writes,
  future Gmail-send, etc.).

---

## Conceptual relationships (text ER)
```
Person ──1:N── Voiceprint
Person ──belongs-to── Scope            (owner→owner-private · guest→guest:{id})
Person ──1:N── Permission ──N:1── Module

Source ──1:N── Document ──1:N── Chunk      (knowledge corpus, scope-tagged)
Module ──1:N── KnowledgeContribution ──produces──▶ Document/Chunk   (the "push")
Chunk ──provenance──▶ Source | Module-record

Person ──1:N── Episode                     (bitemporal raw log)
Episode ──distil(A.U.D.N.)──▶ SemanticFact (temporal, graph)
SemanticFact ──provenance──▶ Episode | Chunk
SemanticFact ──subject_entity_id (soft)──▶ Entity   (person|place|goal; ADR-013 backbone)
EntityAlias ──▶ Entity                     (alias resolution, normalized)
Entity(person).entity_id = person_fact_key (canonical cross-module person pointer)
Module record ──{module, entity_id} (EntityRef)──▶ resolve via ToolRegistry  (never a cross-store join)

Module ──1:1── Manifest ──1:N── Tool
Module ──1:N── ProactiveHook
Teacher (M7-a2) | Curiosity (M7-c) | Capture-graduation (M8-d-c2) ──writes CANDIDATE──▶ Recipe ──owner-gated promote──▶ ENABLED
Module gated-action ──stage──▶ PendingAction ──owner approve──▶ re-dispatch Tool (execute once)

(every Chunk · Episode · SemanticFact · Document carries  scope + sensitivity)
```

## Scope-partition map (the security-load-bearing view)
| Partition (separate encrypted store) | Holds |
|--------------------------------------|-------|
| **`owner-private`** (SQLCipher DB + vector index; key in Secure Enclave, owner-biometric-gated) | Knowledge corpus (owner docs) · all Episodes · owner SemanticFacts · EntityAlias · all module operational stores' sensitive data · **Recipes** (encrypted volume, M7) · **PendingActions** (GATE) |
| **`guest:{person_id}`** (separate per guest) | Tiny semantic preference profile (a few SemanticFacts) only |
| **`general`** (no personal data) | Module registry / Manifests / Tools · `general`-scope capability data (weather, neutral Q&A). (Recipes are owner-private/encrypted, NOT here — M7-a1.) |

`sensitive` data (all `owner-private` + any PII) is **structurally barred from cloud** by the provenance gate;
only affirmatively-`public` data is cloud-eligible; unsure → local.

---

## Modeling decisions made here (override if wrong)
1. **Module-internal operational schema = opaque** — modelled only via `Tool` + `KnowledgeContribution`.
   (Alternative — a central operational schema — rejected: breaks "internals are free" + couples the hub to every module.)
2. **Sensitivity derived from source/scope by default**, with an explicit item-level `public` override; fail-safe→local.
   (Alternative — per-item manual classification everywhere — rejected: error-prone; the safe blanket default is correct.)
3. **Distillation tiers are roles, not tables** — Episode (raw) → SemanticFact (distilled); no separate tier tables.

## Deferred to build (physical-schema spikes)
LanceDB vs SQLite table layout · exact embedding dimension (locked once the embedding model is chosen, phase 5) ·
graph storage (Kuzu vs Mem0 — the memory-primary spike) · index strategy + partition-key enforcement mechanics ·
litestream/SQLite-backup wiring for the backup-ready data dir.

## What this feeds
- **Phase-5 stack re-confirm** — confirms the store choices (LanceDB · SQLite/SQLCipher · the embedding model
  that locks the Chunk/Fact vector dimension) against this model.
- **Phase-6 roadmap → build specs** — these entities become real schemas; the scope-partition map becomes the
  SQLCipher-per-scope + Secure-Enclave-key build task (a security-gated early spec).
