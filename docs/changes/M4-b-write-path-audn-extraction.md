<!-- amended 2026-06-11 per contracts.md (Seam 6) + m3-m4-knowledge-memory.md FLAG F4 -->
<!-- amended 2026-06-17: EmbeddingModel port split embed→embed_documents/embed_query (embedding-layer decision; research/2026-06-17-embedding-implementation.md) -->
---
spec: m4-b-write-path-audn-extraction
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M4-b — Memory write path: atomic-fact extraction (constrained decoding) → top-k semantic search of existing → A.U.D.N. decision (ADD/UPDATE/DELETE/NOOP, grammar-enforced) → bitemporal apply; async/batched; provenance

**Identity:** Implements the mem0-style write path on top of the M4-a bitemporal repository: a turn's text is run through grammar-constrained **fact extraction** (atomic (subject,relation,object) triples) on the local `sensitive_reasoner` role (`Qwen3.6-27B`); each extracted fact is matched against the **top-k existing semantic facts**; the model emits a grammar-constrained **A.U.D.N. decision** (ADD / UPDATE / DELETE / NOOP) per fact; the decisions are applied **non-destructively** through the M4-a repository (ADD=insert, UPDATE=close-interval+insert, DELETE=tombstone, NOOP=nothing), carrying full provenance; the whole pass runs **async/batched** off the interactive turn. Schema/repository = M4-a; recall/auto-inject/decay/owner-surface = M4-c.
→ why: see docs/technical/adr/ADR-004-memory-engine.md (A.U.D.N. write path; constrained decoding; extraction on local teacher; async/batched; provenance) · docs/research/memory-engine-research.md (mem0 algorithm arXiv:2504.19413; small-model merge-judgment is the residual risk → eval-gated).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

<!-- Split rule: ONE logical phase (the extract→match→decide→apply write pipeline) across 3 src files (extraction, the A.U.D.N. decider, the orchestrating write-path/queue) + 1 test. Within bounds. The bitemporal apply primitives (add/update/tombstone) are M4-a's repository — M4-b only CALLS them. Recall/inject/decay/owner is the separate M4-c. The A.U.D.N.-quality on a real small model is a GATED eval task. Flagged per rules. -->

## Assumptions
- M4-a complete: `memory/repository.py` `BitemporalRepository` (`add`, `update`, `tombstone`, `as_of`, `semantic_candidates`, `compute_fact_key`, `append_episode`, `FactRow`), `memory/engine.py` (`open_memory_db`/`DimensionMismatchError`), `memory/store.py` `SqliteMemoryStore`; M0-d `Fact`/`PersonId`/`Scope`/`AsOf`/`EmbeddingModel`/`ModelPort`/`Vector`; M1-b `OpenAIModelPort` (constrained decoding via `complete(role, messages, response_schema=...)` — Outlines, no retry). → impact: Stop (M4-b consumes these exact symbols; the apply step is M4-a's repository, the model calls are the M1-b ModelPort seam).
- **Extraction + A.U.D.N. run on the ONE local-heavy role `sensitive_reasoner`** (model_id `Qwen3.6-27B`, openai adapter, mlx-served lazily), NOT the responder and NOT the cloud teacher (ADR-004 + SHARED CONVENTION). There is NO separate `extractor` role and NO local-teacher role. M4-b calls `model.complete(role="sensitive_reasoner", ...)` via the M0-d/M1-b ModelPort seam (resolved generically by the M1-b adapter; only `claude-cli` is NotImplemented). Sensitive memory extraction is LOCAL — never the cloud `claude-cli` teacher. → impact: Stop.
- **All structured output is grammar-enforced via constrained decoding** (the M1-b `response_schema` seam → Outlines, no validate-retry). Two schemas: (1) the extraction schema (a list of `{subject, relation, object, confidence}` triples); (2) the per-fact A.U.D.N. decision schema (`{op: "ADD"|"UPDATE"|"DELETE"|"NOOP", target_fact_id: str | null, object: str | null, confidence: number}`). The grammar fixes the *format*; the *judgment* (which op) is the residual small-model risk (eval-gated, Task 6). → impact: Stop (no manual JSON-parse-and-retry anywhere; the schema seam is the contract).
- The A.U.D.N. decision is made **per extracted fact against its top-k existing matches** (mem0 algorithm): embed the extracted fact, `repo.semantic_candidates(embedding, k)` (M4-a) restricted to current rows, present the candidates (their `fact_id`+triple) to the model with the new fact, the model returns one decision referencing a candidate `target_fact_id` (for UPDATE/DELETE) or none (ADD/NOOP). → impact: Stop (this is the mem0 ADD/UPDATE/DELETE/NOOP contract).
- **Apply mapping (non-destructive, via M4-a repo):** ADD → `repo.add(...)` (a genuinely new fact); UPDATE → resolve the target row's `fact_key`, `repo.update(fact_key, new_object, ...)` (close interval + insert); DELETE → resolve `fact_key`, `repo.tombstone(fact_key)`; NOOP → nothing. Idempotent re-ingest is M4-a's `add` guard (so re-processing the same turn does not duplicate). → impact: Stop (the apply NEVER destroys history; it only calls the M4-a primitives).
- The pass runs **async/batched off the interactive turn** (ADR-004 "run async/batched"). M4-b exposes an `async def process_turn(...)` that the M1/M4-c turn loop SCHEDULES (fire-and-forget / queued) — it is NOT on the critical response path. M4-b ships an in-process async queue/worker seam (`MemoryWriteQueue`) with a single-flight worker; the actual wiring into the Brain's post-turn hook is M4-c. → impact: Caution (M4-b builds the queue + the processor; M4-c wires it to the turn loop). The episodic raw turn is appended **synchronously and immediately** (cheap, never lost) via `repo.append_episode` before the async extraction runs — so the source history exists even if extraction is deferred/fails.
- **Provenance on every written fact:** `source_turn_id` (the turn that produced it), `extracted_at` (now), `extractor_model` (the served extractor model id), `confidence` (from the decision). These flow into `repo.add`/`repo.update`. → impact: Stop (provenance is an ADR-004 owner-control requirement).
- **Degrade-don't-crash:** extraction/decision failures (model error, malformed-despite-grammar, queue overflow) are caught and logged; a failed turn's episodic row is still persisted; a failed extraction NEVER raises out of the worker (it drops the fact, records a metric). The interactive turn is never blocked or failed by a memory-write error. → impact: Stop (brain.md degrade-don't-crash; memory is best-effort and must not break the conversation).
- Off-hardware: extraction + A.U.D.N. run against a **deterministic `FakeExtractor`/`FakeDecider`** (and a `FakeModelPort` returning schema-valid JSON) so the pipeline + apply + provenance are fully testable without a model; **the real small-model A.U.D.N. accuracy on a labeled set is the GATED eval (Task 6)** — the ADR-004 "small-model merge judgment" residual risk. → impact: Caution (correctness of the pipeline proven off-hardware; quality of the model's judgment is the on-hardware eval).

Simplicity check: considered a validate-and-retry JSON loop instead of constrained decoding — rejected: ADR-004/brain.md lock grammar-constrained decoding (no retry) precisely to fix the small-model JSON-format risk. Considered running extraction synchronously on the turn — rejected: ADR-004 says async/batched (extraction is slow on a local model; it must not add turn latency). Considered making the decider operate over ALL existing facts — rejected: mem0 uses top-k semantic matches (cheap, focused). This is the minimum faithful mem0 write path on the M4-a substrate.

## Prerequisites
- Specs that must be complete first: **M4-a** (repository + engine + store skeleton), **M0-d** (`Fact`/`ModelPort`/`EmbeddingModel`/ports), **M1-b** (`OpenAIModelPort` + constrained-decoding seam). M0-a roles.toml already defines `sensitive_reasoner` (model_id Qwen3.6-27B, openai adapter, mlx lazy) — M4-b reuses it; NO new role.
- Environment setup required: none new off-hardware (reuses M1-b's `outlines`/model client + M4-a's repository). Off-hardware runs on `FakeExtractor`/`FakeDecider`/`FakeModelPort`; **the real served extractor + the A.U.D.N. accuracy eval are GATED on-hardware (Task 6).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/memory/extraction.py | create | `FactExtractor` (grammar-constrained atomic-fact extraction via the `ModelPort` `sensitive_reasoner` role) + the extraction `response_schema` + `ExtractedFact` + `FakeExtractor` |
| /Users/artemis-build/artemis/src/artemis/memory/decide.py | create | `AudnDecider` (grammar-constrained ADD/UPDATE/DELETE/NOOP per fact vs top-k candidates) + the decision `response_schema` + `AudnDecision`/`AudnOp` + `FakeDecider` |
| /Users/artemis-build/artemis/src/artemis/memory/write_path.py | create | `MemoryWritePath.process_turn(...)` (extract→match→decide→apply, provenance) + `MemoryWriteQueue` (async single-flight worker); degrade-don't-crash |
| /Users/artemis-build/artemis/tests/test_memory_write_path.py | create | extraction schema, A.U.D.N. apply mapping (ADD/UPDATE/DELETE/NOOP), provenance, idempotent re-process, async queue, degrade-don't-crash |

## Tasks
- [ ] Task 1: Implement grammar-constrained fact extraction — files: `/Users/artemis-build/artemis/src/artemis/memory/extraction.py` — define frozen `ExtractedFact { subject: str, relation: str, object: str, confidence: float, keywords: tuple[str, ...] = (), contextual_description: str | None = None }` (the A-MEM structured-note fields are written to the M4-a facts columns). Define `EXTRACTION_SCHEMA: Mapping[str, object]` — a JSON-schema for `{"facts": [ {subject, relation, object, confidence(0..1), keywords?(list[str]), contextual_description?(str)} ]}` (the `response_schema` Outlines enforces; keywords/contextual_description are OPTIONAL). <!-- LINT-DEFER 2026-06-11: literal EXTRACTION_SCHEMA dict not inlined (WARN M4-b:21,44); exact JSON-schema strictness flags (additionalProperties/required) are an Outlines-convention design choice, not a mechanical transcription --> `class FactExtractor` constructed with `(model: ModelPort, *, role: str = "sensitive_reasoner")` (# the one local-heavy role; there is no separate 'extractor' role): `async def extract(self, text: str, *, context: str | None = None) -> list[ExtractedFact]` (ASYNC — awaits the async `ModelPort.complete` per the M0-d async-port cascade): build a messages list with a fixed extraction system prompt ("extract atomic, self-contained (subject, relation, object) facts about the owner from the text; subject defaults to 'owner' for first-person statements; no inferences") + the turn `text`; call `await model.complete(role=role, messages=..., response_schema=EXTRACTION_SCHEMA)`; parse the (grammar-guaranteed-valid) JSON into `ExtractedFact`s. `class FakeExtractor` (TEST): deterministic — `async def extract(...)` (matches the async contract) with a tiny rule (e.g. regex "I live in X" → `("owner","lives_in",X)`, "I like X" → `("owner","likes",X)`, "I no longer/used to" → emits a fact tagged for DELETE in the decider fixture) so tests are model-free. — done when: `uv run mypy --strict src` passes; `await FakeExtractor().extract("I live in Paris")` returns one `ExtractedFact("owner","lives_in","Paris", ...)`; `await FactExtractor(...).extract(...)` with a `FakeModelPort` returns the schema's facts.

- [ ] Task 2: Implement the grammar-constrained A.U.D.N. decider — files: `/Users/artemis-build/artemis/src/artemis/memory/decide.py` — define `AudnOp = Literal["ADD","UPDATE","DELETE","NOOP"]`; frozen `Candidate { fact_id: str, subject: str, relation: str, object: str }` (a top-k existing match) and frozen `AudnDecision { op: AudnOp, target_fact_id: str | None, object: str | None, confidence: float }`. Define `DECISION_SCHEMA: Mapping[str, object]` — JSON-schema enforcing `op ∈ {ADD,UPDATE,DELETE,NOOP}`, `target_fact_id` (string|null), `object` (string|null), `confidence` (0..1) (the Outlines `response_schema`). <!-- LINT-DEFER 2026-06-11: literal DECISION_SCHEMA dict not inlined (WARN M4-b:46); exact JSON-schema strictness flags are an Outlines-convention design choice, not a mechanical transcription --> `class AudnDecider` constructed with `(model: ModelPort, repo: BitemporalRepository, *, role: str = "sensitive_reasoner")`: `async def decide(self, new_fact: ExtractedFact, candidates: Sequence[Candidate]) -> AudnDecision` (ASYNC — awaits the async `ModelPort.complete`): FIRST look up `card = repo.cardinality_of(new_fact.relation)` (SYNC local DB — not awaited) (an unknown relation → MAY one-shot-classify via `await model.complete(role="sensitive_reasoner", ...)` then persist `repo.set_cardinality(new_fact.relation, result, source="teacher")` (SYNC); default-MULTI until classified) and pass `card` into the decision prompt. Build messages with the mem0-style decision system prompt — for a SINGLE relation: the rubric as-is (ADD if no candidate is the same (subject,relation); UPDATE if a candidate has the same (subject,relation) but a different object; DELETE if the new fact negates a candidate; NOOP if a candidate already states it); for a MULTI relation: a different object is an ADD of a COEXISTING value (in-place UPDATE is NOT used — DELETE/tombstone-then-ADD only on explicit supersession/negation) + the `new_fact` + the JSON-rendered `candidates`; call `await model.complete(role=role, messages=..., response_schema=DECISION_SCHEMA)`; parse into `AudnDecision`; validate `target_fact_id ∈ candidates` for UPDATE/DELETE (if the model references an unknown id, downgrade UPDATE→ADD / DELETE→NOOP and log — a safety net, not a retry). `class FakeDecider` (TEST): deterministic `async def decide(...)` (matches the async contract) mirroring the rubric over the candidates (same (subj,rel)+diff object → UPDATE targeting that candidate; negation marker → DELETE; identical → NOOP; else ADD). — done when: `uv run mypy --strict src` passes; `await FakeDecider(...).decide(...)` returns UPDATE targeting the right candidate when (subject,relation) matches with a new object, ADD when none match, NOOP when identical.

- [ ] Task 3: Implement the write-path orchestrator + the apply mapping — files: `/Users/artemis-build/artemis/src/artemis/memory/write_path.py` — `class MemoryWritePath` constructed with `(repo: BitemporalRepository, embedder: EmbeddingModel, extractor: FactExtractor, decider: AudnDecider, *, candidate_k: int = 5, extractor_model_id: str = "Qwen3.6-27B")` (the provenance value = the served model id). `async def process_turn(self, text: str, *, turn_id: str, role: str | None = None) -> WritePathResult` where `WritePathResult = { episode_id, facts_added, facts_updated, facts_deleted, noops, errors }`:
  1. `episode_id = repo.append_episode(text, turn_id=turn_id, role=role)` — **synchronous, first, never skipped** (the source history exists even if extraction fails; `repo.append_episode` is a SYNC local-DB write).
  2. `facts = await extractor.extract(text)` (the extractor is now async — awaits the ModelPort).
  3. for each `ef in facts` (wrap EACH in try/except → on error increment `errors`, continue — degrade-don't-crash, never abort the batch):
     a. `emb = (await embedder.embed_documents([f"{ef.subject} {ef.relation} {ef.object}"]))[0]` (the extracted fact triple is STORED text → `embed_documents`, NO query prefix; the same vector is the candidate-search probe AND the vector written by `repo.add`/`repo.update` below; M0-d split port — async, await it).
     b. `cand_pairs = repo.semantic_candidates(emb, candidate_k)` (SYNC local DB — not awaited); materialise into `Candidate`s: for each `(fact_id, distance)` pair, call `repo.get_fact(fact_id)` (SYNC; F4 fix: `BitemporalRepository.get_fact(fact_id) -> FactRow` is defined in M4-a Task 4's method list; use it here instead of `as_of`/ad-hoc lookup) to resolve each `fact_id` to its current triple.
     c. `decision = await decider.decide(ef, candidates)` (the decider is now async — awaits the ModelPort).
     d. **apply** (provenance = `source_turn_id=turn_id, extractor_model=self.extractor_model_id, extracted_at=now`):
        - `ADD` → `repo.add(ef.subject, ef.relation, ef.object, decision.confidence, emb, source_turn_id=turn_id, extractor_model=..., keywords=ef.keywords, contextual_description=ef.contextual_description)` (A-MEM metadata written here; `linked_ids` left empty for a later multi-hop pass).
        - `UPDATE` → resolve `fact_key` from `decision.target_fact_id` via `repo.get_fact(decision.target_fact_id).fact_key` (F4 fix: uses the named primitive); `repo.update(fact_key, decision.object or ef.object, decision.confidence, emb, source_turn_id=turn_id, extractor_model=..., keywords=ef.keywords, contextual_description=ef.contextual_description)`. UPDATE applies to SINGLE-cardinality relations only; a MULTI relation NEVER takes an in-place UPDATE that loses a coexisting value — it is an ADD of a new coexisting value, or tombstone+ADD on explicit supersession (the decider already routes this per cardinality).
        - `DELETE` → resolve `fact_key` from `decision.target_fact_id` via `repo.get_fact(decision.target_fact_id).fact_key` (F4 fix: same named primitive); `repo.tombstone(fact_key)`.
        - `NOOP` → nothing.
     e. tally into the result.
  4. return `WritePathResult`.
  `class MemoryWriteQueue` constructed with `(write_path: MemoryWritePath, *, maxsize: int = 100)`: an `asyncio.Queue`-backed single-flight worker — `def enqueue(self, text, turn_id, role=None) -> None` (non-blocking; if full, DROP + log a metric — memory writes are best-effort, never block the turn); `async def run_worker(self) -> None` (drain loop calling `process_turn`, catching+logging any escape so the worker never dies); `async def drain(self) -> None` (await queue empty — for tests/shutdown). Document: M4-c wires `enqueue` into the Brain's post-turn hook. — done when: `uv run mypy --strict src` passes; `process_turn` applies the four ops correctly via the repo (Task 5); the queue worker processes enqueued turns and survives a `process_turn` exception.

- [ ] Task 4: Re-export + wire into the store seam — files: `/Users/artemis-build/artemis/src/artemis/memory/__init__.py` (modify) — re-export `FactExtractor`, `ExtractedFact`, `AudnDecider`, `AudnDecision`, `AudnOp`, `MemoryWritePath`, `MemoryWriteQueue`, `WritePathResult`. Add a factory `def build_write_path(store: SqliteMemoryStore, model: ModelPort) -> MemoryWritePath` that constructs the extractor/decider/write-path from a `SqliteMemoryStore`'s repository + embedder + the ModelPort (so M4-c gets a one-call constructor); pass the repository into `AudnDecider(model, repo)` for cardinality lookup. Do NOT change the M0-d `Fact` dataclass. — done when: `uv run mypy --strict src` passes; `from artemis.memory import build_write_path, MemoryWriteQueue` succeeds.

- [ ] Task 5: Write the write-path tests — files: `/Users/artemis-build/artemis/tests/test_memory_write_path.py` — typed pytest using the M4-a memory-DB fixture (real keyed DB or plain-sqlite+sqlite-vec fallback), a `FakeEmbedder` (implements BOTH `async def embed_documents` and `async def embed_query` per the split port — the write path calls `embed_documents`), `FakeExtractor`/`FakeDecider` (both with `async def extract`/`async def decide`). Tests calling the async pipeline (`extract`/`decide`/`process_turn`/the queue worker) are `async def` test fns under `@pytest.mark.asyncio` (the M4-a async-test convention) and `await` those calls:
  - extraction: `await FactExtractor(...).extract(...)` over a `FakeModelPort` returning the `EXTRACTION_SCHEMA` shape yields the expected `ExtractedFact`s.
  - **ADD:** `await process_turn("I live in London", turn_id="T1")` → `facts_added==1`; `repo.as_of(now)` has `("owner","lives_in","London")` with `source_turn_id=="T1"`, `extractor_model` set (provenance).
  - **UPDATE (close-interval+insert):** then `await process_turn("Actually I moved to Paris", turn_id="T2")` (FakeExtractor → lives_in Paris; FakeDecider sees the London candidate → UPDATE) → `facts_updated==1`; `as_of(now)` → "Paris"; `history(fact_key)` has 2 rows, the London row's `tx_to` CLOSED (never hard-deleted), `source_turn_id` of the Paris row =="T2".
  - **DELETE (tombstone):** `await process_turn("I don't live in Paris anymore", turn_id="T3")` (→ DELETE) → `facts_deleted==1`; `as_of(now)` returns nothing for the key; `history(fact_key)` still has the prior rows (never-hard-delete).
  - **NOOP:** re-processing "I live in Paris" when Paris is already current → `noops>=1`, row count unchanged.
  - **idempotent re-process:** running the SAME turn twice (same `turn_id`+text) does not duplicate facts (M4-a `add` idempotency / NOOP).
  - **episodic-first:** after any `process_turn`, `repo.read_episodes()` contains the turn's `text` (persisted even if a per-fact apply failed).
  - **degrade-don't-crash:** inject an extractor that raises for one fact → `process_turn` returns with `errors>=1` and does NOT raise; the episode row still exists.
  - **async queue:** `MemoryWriteQueue.enqueue(...)` ×N then `await drain()` → all N turns applied; a `process_turn` that raises does not kill the worker (a later enqueue still processes).
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_memory_write_path.py` passes.

- [ ] Task 6 (GATED — on-hardware, the ADR-004 small-model A.U.D.N. eval): Real extractor + A.U.D.N. accuracy on a labeled set — files: `/Users/artemis-build/artemis/tests/eval/audn_eval.py` (a script, not a unit test) + a small labeled fixture `/Users/artemis-build/artemis/tests/eval/audn_cases.jsonl` (hand-authored: ~30–50 turn→expected-(op,triple) cases covering ADD/UPDATE/DELETE/NOOP, including the tricky negation + paraphrase + multi-fact cases) — on the Mini with the served local `sensitive_reasoner` (Qwen3.6-27B) MLX model + Outlines (the locked reasoner is already 27B; the eval validates its A.U.D.N. judgment, not a role choice): run `FactExtractor`+`AudnDecider` over the labeled cases through the REAL `OpenAIModelPort`, score extraction-triple match + decision-op accuracy, and report a confusion matrix over the four ops. This is the ADR-004 "small-model merge judgment" residual-risk probe — it informs whether the served model is large enough (ADR-004 warns reliable extraction may want a heavier model). Also: decay half-life tuning is M4-c; this task ONLY evals extraction+decision quality. — done when: the eval runs on the Mini, the op-accuracy + confusion matrix are recorded in handoff, and a go/no-go on the served extractor model size is noted (flag if a heavier model is needed).

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/memory/extraction.py, /Users/artemis-build/artemis/src/artemis/memory/decide.py, /Users/artemis-build/artemis/src/artemis/memory/write_path.py, /Users/artemis-build/artemis/tests/test_memory_write_path.py, /Users/artemis-build/artemis/tests/eval/audn_eval.py, /Users/artemis-build/artemis/tests/eval/audn_cases.jsonl |
| Modify | /Users/artemis-build/artemis/src/artemis/memory/__init__.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_memory_write_path.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fakes + M4-a DB fixture) |
| `uv run python tests/eval/audn_eval.py` (GATED, on-Mini) | A.U.D.N. accuracy eval over the labeled set |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/memory/extraction.py, src/artemis/memory/decide.py, src/artemis/memory/write_path.py, src/artemis/memory/__init__.py, tests/test_memory_write_path.py, tests/eval/** |
| `git commit` | "feat: M4-b memory write path — constrained extraction → top-k → A.U.D.N. decision → bitemporal apply (async/batched, provenance)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (sensitive_reasoner role endpoint, embedder) |

### Network
| Action | Purpose |
|--------|---------|
| local `127.0.0.1` calls to the served sensitive_reasoner (Qwen3.6-27B) MLX model (GATED) | Live extraction + A.U.D.N. decision |

## Specialist Context
### Security
Extraction + A.U.D.N. run on the **local** `sensitive_reasoner` role (Qwen3.6-27B; per the sensitivity router) — the owner's turn text never leaves the device for memory extraction. The turn text and extracted facts are sensitive: NEVER log the fact `object` or episode `text` at info level (provenance ids only). The write path only calls the M4-a non-destructive primitives — a prompt-injected or hallucinated decision can at worst tombstone/add a fact (recoverable via history + the M4-c owner surface), never hard-delete. Ingested/turn content is untrusted data: the decider scores/decides over it but the grammar constrains the output to the four ops + a candidate id (it cannot emit arbitrary SQL/actions). [FLAG for apex-security (M4 gate): confirm no turn/fact plaintext is logged; confirm the unknown-`target_fact_id` downgrade safety net; review the prompt-injection surface of the extraction/decision prompts.]

### Performance
The pass is **async/batched off the interactive turn** (ADR-004) — the episodic append is the only synchronous, cheap step; extraction+decision (slow local-model calls) run on the queue worker, never on the response path. `candidate_k` (default 5) bounds the decision context. Re-ingest is idempotent (M4-a) so re-processing is cheap. The A.U.D.N. model-size/latency trade-off is the Task-6 eval subject.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/memory/extraction.py, decide.py, write_path.py | Type + docstring all exports; document the grammar-constrained no-retry contract, the A.U.D.N. apply mapping, the async/best-effort/degrade-don't-crash semantics, provenance fields, the unknown-id downgrade safety net |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_memory_write_path.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_memory_write_path.py` → verify: ADD/UPDATE(close-interval)/DELETE(tombstone)/NOOP apply correctly with provenance; episodic-first persistence; idempotent re-process; degrade-don't-crash (no raise on a failing fact); async queue drains and survives a worker exception.
- [ ] Run `uv run python -c "from artemis.memory import build_write_path, MemoryWriteQueue, AudnDecider, FactExtractor; print('ok')"` → verify: prints `ok`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Task 6: A.U.D.N. eval runs over the labeled set; op-accuracy + confusion matrix + extractor-model go/no-go recorded → verify in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
