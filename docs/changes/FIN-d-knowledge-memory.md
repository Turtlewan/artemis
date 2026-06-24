---
spec: fin-d-knowledge-memory
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave S · NEW · last in FIN-a→b→c→d. Implements the finance knowledge/memory push: durable
     NON-record facts ("owner pays ~$X/mo for Y", recurring merchants, spending patterns) → M4 memory +
     M3 knowledge. RAW financial records do NOT go to memory (memory excludes financial). The ADR-029
     sensitivity tag rides every push (finance facts = sensitive → kept off cloud by the enforcer),
     reusing the SENS-prod-M4b tagging. Always-local. cross_model_review: true (sensitivity-tagged egress). -->

# Spec: FIN-d — Finance knowledge/memory push (durable non-record facts → M4/M3, sensitivity-tagged)

**Identity:** The Finance → core knowledge bridge — derive durable, non-record financial facts (recurring-spend summaries, recurring merchants, spending patterns) from the FIN-a/b/c ledger and push them to M4 memory + the M3 knowledge corpus, stamping each with the ADR-029 `sensitivity="sensitive"` tag so the RAG-compose enforcer keeps them off any cloud prompt. Raw transaction records are explicitly excluded from the push.
→ why: see docs/technical/modules/finance.md (Knowledge / memory push) · docs/findings/cluster-decisions/finance.md (F-a) · docs/technical/adr/ADR-029-sensitivity-ingestion-gate.md (the tag the push inherits) · docs/technical/adr/ADR-022 (always-local).

## Assumptions

- **FIN-a/b/c** complete: `FinanceStore`/`FinanceRepository` with `list_subscriptions`, `spend_summary`/`total_spend` (transfers excluded), `list_transactions`, `recurring_candidates`; FIN-c's `detect_recurring` produces hardened `subscription` rows; the always-local invariant holds. → impact: Stop (FIN-d reads the ledger to derive *summary facts*, never copies raw records).
- **M4-b** complete: `MemoryWriteQueue.enqueue(text: str, turn_id: str) -> None` (or the post-SENS-prod-M4b signature carrying sensitivity); `build_write_path` factory. The SENS-prod-M4b amendment added a `sensitivity`/`category` to the fact write path. → impact: Stop (FIN-d enqueues summary facts with `sensitivity="sensitive"`).
- **M3-a** complete: `IngestPipeline.ingest(source: Source) -> IngestResult` (async per ADR-015); `Source(kind, uri, scope)`; the SENS-prod-M3a amendment added per-source `sensitivity` tagging on the Document/chunk/LanceDB row. → impact: Stop (FIN-d ingests summary-text documents into the knowledge corpus with `sensitivity="sensitive"`).
- **ADR-029 / SENS-prod-M4b + SENS-prod-M3a** complete: the `sensitivity: Literal["general","sensitive"]` field exists on the memory fact write path AND the ingestion Document. Finance facts are inherently sensitive (finance category) → FIN-d passes `sensitivity="sensitive"` EXPLICITLY rather than relying on the classifier (a finance fact is sensitive by construction; skip the per-source classify call — cheaper + fail-safe). → impact: Stop (the tag rides every FIN-d push so the enforcer keeps finance facts off cloud; this is the load-bearing privacy contract).
- **memory-excludes-financial (finance.md / owner-rules):** RAW financial records (individual transactions, amounts, merchants-with-amounts) do NOT go to memory. Only DURABLE NON-RECORD facts ("owner pays ~$X/mo for Netflix", "owner has N active subscriptions", "owner's typical monthly dining spend ≈ $Y") are pushed. The owner-rules already exclude finance/health from the general memory pipeline; FIN-d's push is the *deliberate, sensitivity-tagged* exception for cross-domain recall (kept local by the enforcer). → impact: Stop (the push is summary-facts-only; never a raw-record dump).
- **Always-local (ADR-022/F-D13):** FIN-d derives facts deterministically (or via the LOCAL `sensitive_reasoner` for phrasing) and pushes to LOCAL memory/knowledge stores. No cloud/Codex import. The sensitivity tag ensures even the pushed facts never reach cloud later. → impact: Stop.
- **M2-stub on dev:** `FakeMemoryWriteQueue` (records enqueues + sensitivity) + `FakeIngestPipeline` (records ingests + sensitivity) for off-hardware tests. → impact: Low.

Simplicity check: considered pushing every transaction as a memory fact — rejected outright (memory excludes financial records; that would be a privacy + noise disaster). Considered an LLM to summarise the whole ledger — rejected; the durable facts are a small deterministic derivation (subscription list → "pays ~$X/mo for Y"; spend_summary → "typical monthly dining ≈ $Y"). The minimum is a `derive_finance_facts` deterministic step + a sensitivity-tagged push helper.

## Prerequisites

- Specs complete: **FIN-a/b/c**, **M4-b** (+ SENS-prod-M4b), **M3-a** (+ SENS-prod-M3a), **ADR-029** sensitivity gate (producer half).
- Environment: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/finance/knowledge.py` | create | `derive_finance_facts(store) -> list[FinanceFact]` + `push_finance_knowledge(facts, *, ingest, memory_queue)` (sensitivity-tagged) |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py` | modify | add `finance_knowledge_push` trigger callable (manual + scheduled) |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` | modify | wire the ingest pipeline + memory queue into the manifest (injected) + the new ToolSpec |
| `/Users/artemis-build/artemis/tests/test_finance_knowledge.py` | create | derive facts (no raw records), sensitivity tag rides push, memory-excludes-financial-records, degrade |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: `derive_finance_facts`** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/knowledge.py` —

  ```python
  @dataclass(frozen=True)
  class FinanceFact:
      text: str                # the durable NON-record fact, e.g. "Owner pays ~$15.99/mo for Netflix."
      kind: Literal["subscription", "recurring_merchant", "spending_pattern"]
      key: str                 # a stable identity for dedup/update (e.g. f"subscription:{merchant}")
  ```

  `def derive_finance_facts(store: FinanceStore) -> list[FinanceFact]`:
  - **Subscriptions:** for each active `subscription` → `FinanceFact(text=f"Owner pays ~${amount}/{cadence} for {merchant}.", kind="subscription", key=f"subscription:{merchant}")`.
  - **Recurring merchants:** frequent purchase merchants (from `recurring_candidates`) without a subscription → `FinanceFact(text=f"Owner regularly spends at {merchant}.", kind="recurring_merchant", key=f"merchant:{merchant}")`.
  - **Spending patterns:** from `spend_summary(start=<trailing-window start ISO>, end=<now ISO>, group_by="category")` over the trailing period (FIN-a froze `spend_summary(*, start, end, group_by)` with `start`/`end` REQUIRED — e.g. a trailing-90-day window: `start=(today-90d).isoformat()`, `end=today.isoformat()`) → `FinanceFact(text=f"Owner's typical monthly {category} spend is around ${rounded}.", kind="spending_pattern", key=f"pattern:{category}")` for the top categories.
  - **NEVER** emit a fact containing a specific transaction id, a one-off purchase, or a raw amount tied to a single txn — only AGGREGATE/RECURRING summaries (the memory-excludes-records rule). Round amounts to avoid leaking exact figures.

  — done when: `uv run mypy --strict src` passes; `derive_finance_facts` over a store with 1 subscription + a dining-spend history returns a `subscription` fact + a `spending_pattern` fact; NO fact references a single transaction id or a one-off purchase; amounts are rounded/aggregate.

- [ ] **Task 2: `push_finance_knowledge` (sensitivity-tagged)** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/knowledge.py` —

  `async def push_finance_knowledge(facts: list[FinanceFact], *, ingest: IngestPipeline, memory_queue: MemoryWriteQueue, settings: Settings) -> int`:
  - For each fact:
    - **Memory push:** `memory_queue.enqueue(fact.text, turn_id=f"finance:{fact.key}")` — but the SENS-prod-M4b path tags the fact `sensitive`. **FIN-d passes `sensitivity="sensitive"` explicitly** (finance is sensitive by construction). If the post-SENS-prod-M4b `enqueue` signature accepts a `sensitivity` kwarg, pass it; otherwise the fact text is classified by the SENS-prod-M4b classifier which will tag finance text sensitive anyway — but the EXPLICIT pass is preferred (cheaper, fail-safe). Document the exact kwarg against SENS-prod-M4b's final signature.
    - **Knowledge push:** write the fact text to a staging file under `paths.scope_dir(settings, OWNER_PRIVATE) / "ingest-staging"` (the M8-d-c2 staging-dir pattern — NOT system /tmp, which the M3-a `FileConnector` rejects), then `await ingest.ingest(Source(kind="file", uri=str(staging_path), scope=OWNER_PRIVATE))`. The SENS-prod-M3a per-source tagging stamps the Document `sensitive` (finance text classifies sensitive); FIN-d may also pass an explicit sensitivity override if SENS-prod-M3a exposes one. Clean up the staging file after.
  - Degrade-don't-crash: wrap each push in try/except → log a warning (no fact text) + continue; a failed push never aborts the others or the caller.
  - Return the count of facts pushed.

  **Sensitivity invariant (inline comment):** `# PRIVACY: every finance fact is pushed with sensitivity="sensitive" (ADR-029). The RAG-compose enforcer (SENS-enforce-ragcompose) will keep these facts out of any cloud prompt. A finance fact must NEVER be tagged "general".`

  — done when: `uv run mypy --strict src` passes; `await push_finance_knowledge(facts, ...)` enqueues each fact to the `FakeMemoryWriteQueue` with `sensitivity="sensitive"` (asserted) and ingests each via the `FakeIngestPipeline` with the document tagged sensitive; a failing push degrades without aborting the rest.

- [ ] **Task 3: Tool + manifest wiring** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py`, `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` (modify) —

  Add `finance_knowledge_push` callable (ADR-016 async; READ-derives + WRITE-pushes → `ActionRisk.WRITE`): derives facts via `derive_finance_facts` then `await push_finance_knowledge(...)`. Wire module-level `_ingest`/`_memory_queue`/`_settings` + `init_finance_knowledge(ingest, memory_queue, settings)` (called by `finance_manifest`, mirroring M8-d-c2's `init_capture`). Add the ToolSpec. The push also runs on a schedule (the FIN-c spending-summary hook can trigger it, OR a periodic call — reference; the tool is the manual + scheduled entry point).

  Update `finance_manifest` signature to accept `ingest_pipeline`/`memory_queue` (injected at composition, like M8-d-c2). All AUTO (no GATE).

  — done when: `uv run mypy --strict src` passes; `finance_knowledge_push` is a coroutine function; `finance_manifest(store, registry, ingest, memory_queue)` includes the tool; `finance_knowledge_push` raises `RuntimeError` if the handles are unset.

- [ ] **Task 4 (GATED — on-hardware):** real M4 memory + M3 knowledge: `finance_knowledge_push` enqueues subscription/pattern facts to the real memory write queue (tagged sensitive) and ingests them into the real LanceDB knowledge corpus (Document tagged sensitive); confirm via a later RAG-compose run that the finance fact is HELD BACK from a cloud-eligible query (the enforcer filters it) — the end-to-end privacy proof. — done when: recorded in handoff.

- [ ] **Task 5: Tests** — files: `/Users/artemis-build/artemis/tests/test_finance_knowledge.py` — typed pytest, FIN-a store (fallback sqlite), `FakeMemoryWriteQueue` (records `(text, turn_id, sensitivity)`), `FakeIngestPipeline` (records `(source, sensitivity)`), `Settings(data_root=tmp_path)`.

  - **derive facts:** a store with 1 subscription + dining history → a `subscription` fact + a `spending_pattern` fact; assert NO fact text contains a single transaction id or a one-off purchase amount (memory-excludes-records); amounts are aggregate/rounded.
  - **sensitivity rides the push:** `await push_finance_knowledge(facts, ...)` → every `FakeMemoryWriteQueue` enqueue carries `sensitivity="sensitive"`; every `FakeIngestPipeline` ingest's Document is tagged sensitive. Assert NO finance fact is ever tagged `"general"`.
  - **memory-excludes-financial-records:** a raw transaction is NEVER enqueued (only derived summary facts) — assert the enqueued texts are all `FinanceFact.text` summaries, none a raw txn dump.
  - **degrade:** a `FakeMemoryWriteQueue.enqueue` that raises → the other facts still push; `push_finance_knowledge` returns the successful count without propagating.
  - **always-local guard:** the finance package imports no cloud/Codex port.

  — done when: `uv run pytest -q tests/test_finance_knowledge.py` passes AND `uv run mypy --strict src tests/test_finance_knowledge.py` passes AND ruff clean.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/knowledge.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` |
| Create | `/Users/artemis-build/artemis/tests/test_finance_knowledge.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_finance_knowledge.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_finance_knowledge.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/finance/{knowledge,tools,manifest}.py`, `tests/test_finance_knowledge.py` |
| `git commit` | `"feat: FIN-d finance knowledge/memory push — durable non-record facts, sensitivity-tagged (ADR-029)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution (staging dir + memory/knowledge stores) |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | LanceDB/memory writes are local; real stores GATED on-Mini |

## Specialist Context

### Security

- **Sensitivity-tagged egress (ADR-029):** every finance fact is pushed with `sensitivity="sensitive"` (explicit, by construction — finance is sensitive). The RAG-compose enforcer (SENS-enforce-ragcompose) keeps these facts out of every cloud prompt. A finance fact must NEVER be tagged `general` — asserted in tests. This is the load-bearing privacy contract.
- **Memory excludes raw records:** only DURABLE AGGREGATE facts are pushed (recurring spend, subscription list, category patterns) — never individual transactions, amounts-per-txn, or one-off purchases. The owner-rules already exclude finance from the general memory pipeline; FIN-d's push is the deliberate, sensitivity-tagged, summary-only exception for cross-domain recall.
- **Always-local (ADR-022/F-D13):** derivation is deterministic/local; the push targets LOCAL memory/knowledge stores; the sensitivity tag keeps the facts local downstream. No cloud/Codex import.
- **Staging-dir hygiene (M8-d-c2 precedent):** the knowledge-push staging file is written under `scope_dir/ingest-staging`, NOT system /tmp (the M3-a `FileConnector` rejects /tmp), and cleaned up after ingest.
- **Degrade-don't-crash:** a failed push never aborts the others or the caller; no fact text is logged.

[apex-security review (cross_model_review): confirm every finance fact carries `sensitivity="sensitive"` (never general); confirm no raw transaction record is pushed to memory; confirm no cloud import; confirm the staging file is cleaned up.]

### Performance

- `derive_finance_facts` is a handful of indexed reads + a deterministic summarisation — cheap, run on a schedule (the FIN-c spending-summary hook or a periodic call), never the interactive turn. The push is N small enqueues + N small ingests, off the hot path (the memory queue is async; the ingest is best-effort).

### Accessibility

(none — no frontend in FIN-d)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/finance/knowledge.py` | Docstring `derive_finance_facts` (summary-facts-only, no raw records), `push_finance_knowledge` (sensitivity-tagged, degrade-don't-crash, staging-dir hygiene), the never-general finance-fact invariant |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_finance_knowledge.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_finance_knowledge.py` → verify: derive produces summary facts (no raw records / no single-txn ids / aggregate amounts); every push carries `sensitivity="sensitive"` (never general); raw transactions never enqueued; degrade-don't-crash; no cloud import.
- [ ] `uv run python -c "from artemis.modules.finance.knowledge import derive_finance_facts, push_finance_knowledge, FinanceFact; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) facts push to real memory + knowledge tagged sensitive; a later RAG-compose holds the finance fact back from a cloud query → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
