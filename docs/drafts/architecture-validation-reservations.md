# Draft — Architecture-validation reservation decisions (2026-06-23)

_Closing out the architecture-validation research (`docs/research/2026-06-23-architecture-validation/` reports 01–04). Walking through reservations **A–H + 2 doc lines (I, J)**, deciding each; **edits are HELD to the end** (owner chose "walk through every call before editing"). **No spec/ADR edits applied yet.**_

## Decisions made (locked this session)

| # | Reservation | Decision | Lands in |
|---|---|---|---|
| **A** | `derived` provenance | **RESERVE** — add `source_kind="derived"` + `source_ref` (fact-id list) + reserve `derivation_method`/`confidence` | M4-a facts schema + ADR-004 |
| **B** | MemoryStore port not triple-only | **RESERVE (keep port open)** — recipes handle action-skills; port stays record-type-generic so a future `procedure` record (steps/preconditions/success-criteria) can be added | M4 port + ADR-004 |
| **C** | async-write-default + multi-scope tags | **CONFIRM + MAKE EXPLICIT** in the MemoryStore port contract (verify vs ADR-015; assert so it can't regress) | M4 port |
| **D** | RAPTOR summary-tree fields | **RESERVE** — `node_level`/`is_summary` + parent/child link on chunk/doc schema (don't build summarizer now) | M3-a |
| **E** | structured-projection ingest hook | **RESERVE** — ingest hook + minimal queryable side table for aggregates (text-to-SQL target); don't build extractor now | M3-a |
| **F** | durable-execution model | **CHECKPOINT + REPLAY (shared)** — one thin checkpoint-after-step + replay model + a **shared idempotency-key convention** across Task Executor / heartbeat / recipe-runner; OBS/GATE logs cover audit; v1 may stub the impl | ADR-024 (+ M6, M7 notes) |
| **G** | planner / long-horizon mode | **RESERVE first-class router→planner escalation seam (port)** — peer to the router; v1 realized via the Task Executor | ADR-024 + M1 |
| **H** | cloud-reasoner fallback ladder + recipe-quality gate | **BOTH** (see below) | ADR-022/027 + M7 + distill pipeline |

### H detail
- **Fallback ladder (non-sensitive only; sensitive never escalates to cloud — ADR-022 wall):**
  - Rung 1 (primary) = **Codex gpt-5.5** (ChatGPT subscription, ADR-027)
  - Rung 2 (alt-cloud) = **DeepSeek Pro API** — pay-per-token, API-not-subscription (dodges CLI/OAuth fragility), vendor diversity; only ever sees non-sensitive data
  - Rung 3 = **local model** (see OPEN item below)
  - Keep `ModelPort` provider-agnostic; port open to add more rungs.
- **Recipe-quality gate + re-seed path** — teacher-quality-aware gate before a distilled recipe is promoted (beyond the existing replay-verify + recurrence gate), so a degraded/unavailable teacher during seeding can't permanently imprint the local recipe library; add a refresh/re-seed path for recipes authored under a weak teacher.

## Remaining decisions — RESOLVED 2026-06-23

| # | Reservation | Decision | Landed in |
|---|---|---|---|
| **H·3** | Rung-3 local reasoner | **Qwen3-Instruct = documented default** (snappy, instruction-tuned); tiered ~8B dev → ~32B Mac; the final Instruct-vs-R1-distill checkpoint is **benchmark-confirmed at Mac bring-up** (reversible swap behind `ModelPort`, not a fork) | ADR-022 § Refinement 2026-06-23 |
| **2** | Voice (M5) + portfolio fit | Voice picks **not re-opened** (Parakeet/Kokoro/FluidAudio-Sortformer/SmartTurn, locked, sound). Real concern = VRAM budget: **64GB reaffirmed** as highest-leverage call + **reserve a model-residency/load-evict convention** (tied to F). Owner directive: **dev-box budget produced** (RTX 5060 Ti 8GB → develops every component + ambient set + one medium model + voice, but NOT heavy reasoner+vision+voice all hot → dev box itself needs the load/evict manager) | ADR-022 § Refinement 2026-06-23 + brain.md § Inference |
| **I** | Parametric-memory stance | Recorded: **no runtime weight-learning; sole parametric write-path = offline Codex-distilled `sensitive_reasoner` (ADR-022)** | ADR-004 + brain.md § Self-improvement |
| **J** | Prospective-memory home | **No new store** — time-anchored → scheduled Task (M8-d); condition-anchored → ADR-021 reaction; both fire via Heartbeat (M6); task-memory (ADR-024) = execution state, not the intention | brain.md § Memory |

## APPLIED 2026-06-23 (all A–J landed)
- **ADR-004** — A (`derived` provenance enum + `source_ref` list + reserved `derivation_method`/`derivation_confidence`), B (record-type-generic port), I (parametric stance). + Decision-table provenance row updated.
- **M4-a** — A schema migration note (folds `derived` into the deferred typed-source-ref migration).
- **M0-d** — B (record-type-generic docstring) + C (async-write-default + scope-on-every-method, with a regression-guard verification).
- **M3-a** — D (`node_level`/`is_summary`/`parent_chunk_id` reserved on `ChunkRecord` + VectorStore row) · E (`projection_fn` ingest hook + reserved side table).
- **ADR-024** — F (shared checkpoint/replay + idempotency-key convention across Task Executor / heartbeat / recipe-runner) · G (first-class `router → planner` escalation seam).
- **M1-b** — G (the `escalate` path reserved as the planner seam; `path` kept an open-set discriminant).
- **M6-a** — F (dedup_key aligned to the shared convention + per-tick lock reserved).
- **M7-a2** — F (recipe-runner effect path idempotency-key-ready).
- **ADR-022 § Refinement 2026-06-23** — H1 (fallback ladder Codex → DeepSeek-Pro-API → local Qwen3-Instruct) · H2 (recipe-quality gate + re-seed) · model-residency budget + 64GB reaffirm + dev-box VRAM table.
- **M7-b** — H2 (teacher-quality field + `needs_reseed` flag + re-seed path reserved).
- **distill-datagen-pipeline** — H2 (re-seed/refresh mode reserved) + sensitive-domain-categories pending note.
- **brain.md** — I (§ Self-improvement) · J (§ Memory) · portfolio/residency pointer (§ Inference).

## Where I stopped — COMPLETE
- **All reservations A–J decided AND applied** across the 12 files above. `04-seven-memory-types.md` committed.
- **ADR-027 — RESOLVED 2026-06-23 (no Artemis ADR needed).** 027 is an **intentional Artemis numbering skip** — it is an **APEX-system** ADR (the build-system coder policy), documented as such in the overview ADR index ("027 = APEX-system ADR"). On the Artemis side there is no gap: runtime reasoning-engine routing = **ADR-022** (+ the H1 ladder in its §Refinement 2026-06-23); build coder = **ADR-026**; the `composite-model-routing` decision is covered by ADR-022. (The APEX-system ADR-027 file itself doesn't exist either, but that is an APEX-system citation matter, not an Artemis-corpus item; owner left it as-is — CLAUDE.md prose already states the policy.)
- **Next:** commit the application wave (owner-gated); update status.md In-Flight + Open Question (done this session).
