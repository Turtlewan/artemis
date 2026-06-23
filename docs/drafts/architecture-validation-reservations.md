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

## OPEN — not yet decided (resume here)

1. **H · Rung 3 — local reasoner family/sizing.** Leaning: **Qwen3 family**, hardware-tiered (~8B on the current dev box → ~32B-class on the 64GB Mac), **Codex-distilled adapter for the sensitive path** (ADR-022). Undecided checkpoint: **Qwen3-Instruct** (snappy, recommended) vs **DeepSeek-R1-Distill-Qwen** (reasoning-tuned, slower) vs **decide-at-Mac-bring-up** (benchmark on real 64GB). NOTE: "DeepSeek-distilled local" is usually a *Qwen base* anyway → not a foundational fork, just a checkpoint swap behind the same runtime.
2. **Voice model (M5) + local-model-portfolio fit** — owner raised: the voice stack (STT Whisper-family · TTS Kokoro/Piper · speaker-ID ECAPA/pyannote for the voice-Tier gate) lives in M5 + its own `docs/research/` voice doc (pull it up on resume; don't quote locked picks from memory). The real cross-cutting concern report 03 flagged: **does the whole local-model portfolio (reasoner + embeddings + reranker + visual + STT + TTS + speaker-ID) fit + coexist on 48–64GB** — a VRAM-budget question, strongest argument for the 64GB call.
3. **I (doc-only) — parametric-memory stance.** Record one line in ADR-004/brain.md: *no runtime weight-learning; the sole parametric write-path is the offline Codex-distilled `sensitive_reasoner` (ADR-022).* So it's never re-litigated as an oversight.
4. **J (doc-only) — prospective-memory representation.** Confirm one canonical home across heartbeat / ADR-021 reactions / tasks / ADR-024 task-memory; watch-list note, **no new store**.

## Then — APPLY (only after the open items are decided)
Amend, in one pass: **M3-a** (D, E) · **M4-a** (A) · **M4 MemoryStore port** (B, C) · **ADR-004** (A, B, I) · **ADR-024** (F, G) · **M1** (G) · **M6 + M7** (F notes) · **ADR-022/027 + M7 + distill pipeline** (H) · **brain.md** (I) · prospective note (J).
Also: **`04-seven-memory-types.md` is committed**; this draft + status row are the live checkpoint.

## Where I stopped
- **Decided:** A, B, C, D, E, F, G, H (ladder rungs 1–2 + quality gate).
- **Next question to resolve:** H rung-3 local-model checkpoint (Qwen3-Instruct vs R1-distill-Qwen vs decide-at-Mac).
- **Open items:** rung-3 local model · voice/portfolio discussion · I · J · then apply all edits.
