# ADR-022 — Model & runtime re-architecture: on-demand cloud reasoning + local-trigger proactivity + composed harness

- **Status:** **Accepted** — privacy-routing policy resolved 2026-06-22 = **hybrid** (sensitive → local, rest → Codex/cloud; the wall is kept). **Refined 2026-06-22:** sensitivity gate = a local model (not regex); sensitive reasoner = Codex-distilled; phased build — see § Refinement.
- **Date:** 2026-06-22
- **Deciders:** owner + planning
- **Relates:** ADR-001 (stack — local-model portfolio/MLX **retained** for the *sensitive* path; non-sensitive → cloud) · ADR-002 (deployment — build-Windows-first; Mac = host + sensitive-model box) · ADR-003 / ADR-005 / ADR-006 (the privacy wall — **RETAINED** under the hybrid policy) · ADR-004 (memory) · ADR-023 (Tauri client) · ADR-024 (task executor). Research this session: agent-framework comparison, the OpenClaw/Hermes harness ecosystem, the Codex-subscription / third-party-harness bans.

## Context
A re-look prompted by *"use agent harnesses + OpenAI"* concluded: **don't** cloud-pivot the whole system, and **don't** build on a third-party harness (Hermes / OpenClaw) — but **do** (a) move the heavy-reasoning **model layer** to cloud OpenAI called **on-demand**, (b) keep **proactivity** via a cheap **always-on local trigger**, and (c) **compose** the harness from best-of-breed layers rather than adopt one framework. Findings that drove this: the OpenAI **subscription *does* run agents** — via **Codex** (`codex exec` / SDK on ChatGPT sign-in), which OpenAI permits for **personal** use (the harness bans hit third-party *products*, not an individual on their own machine); it rides an **undocumented, rate-capped** backend, so it is taken as a **pluggable default with local/metered-API fallback**, not a hard dependency. Hermes is immature, security-leaky (skill-poisoning, unauth API), has no privacy model, and is API-only → borrow its *patterns*, don't build on it.

## Decision (settled sections)

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Reasoning engine (routed by sensitivity, pluggable)** | **Non-sensitive → Codex on the ChatGPT subscription** (default; `codex login` → `codex exec` / SDK; plan quota, no per-token bill; OpenAI permits personal use). **Sensitive tasks (finance/health/journal/memory) → a LOCAL model** (8B on the RTX 5060 Ti in dev / 27B on the Mac in prod) — never leave the box. The existing **sensitivity router** decides; both sit behind a pluggable `ModelPort` / Pydantic-AI seam (the cloud path falls back to local / metered-API). Per-task map in `roles.toml`. |
| 2 | **Proactivity** | A tiny **always-on LOCAL heartbeat** (scheduler + optional local 4B triage) decides *when* to act, then **fires the cloud model on-demand** for the heavy thinking. Idle ≈ free; **subscription-quota usage** scales with *meaningful activity* (keeping you under Codex's 5-hour/weekly caps). The full proactive engine (digest · triage · reactions · background executor) is preserved. |
| 3 | **Embeddings** | Stay **LOCAL** (Ollama `qwen3-embedding:0.6b`, 1024 dims; reranker local too) — free, high-volume, dimension-locked. The same model serves dev (Ollama/Windows) and prod (MLX/Mac) behind the `EmbeddingModel` port. |
| 4 | **Harness composition** ("splice" done right) | **Own a thin `plan→act→verify` spine** (state in task-memory; borrow LangGraph's *checkpoint + interrupt* patterns — task-memory = checkpoint, GATE = interrupt — **not** its runtime). **Pydantic AI** for typed agent/step calls (model-agnostic; pending a constrained-decoding integration check). **MCP** at the tool edges. **OpenTelemetry** for observability. Borrow Hermes's **GEPA** self-improving-skill technique + its layered-memory interface **into the recipe system with Artemis's safety gates**. |
| 5 | **Build strategy** | Build ~the **full app on Windows first** (cloud agents = API calls; local triage on the RTX 5060 Ti 8 GB); buy the **Mac last**, only as the always-on host. **Supersedes the batch-handoff strategy**; reclassifies ~60 "Mini-gated" specs as Windows-buildable. |
| 6 | **Per-turn memory loop** | `summarize (cheap model) → embed (local Qwen3) → store (sqlite-vec)`; the A.U.D.N. semantic layer + the executor's task-memory layer build on top. **ADR-004 structure unchanged.** |

### Engine conditions accepted (Codex-subscription default)
Taken **eyes-open**: (a) Codex is a **coding** agent — strong for tool/code tasks, off-label as a general chat engine (raw GPT-5.x on subscription means the **undocumented backend**); (b) **rate-capped** — 5-hour rolling windows + weekly quotas per plan (Pro $100/$200 = 5×/20× headroom; the local trigger keeps usage under the cap); (c) **fragile** — the programmatic-subscription path rides an undocumented backend OpenAI can change without notice and is unsupported for automation. The **pluggable seam + local/API fallback is therefore mandatory, not optional** — it is what makes the subscription bet safe. Artemis **orchestrates** Codex as a swappable engine; it is **not built *on*** Codex.

## Privacy-routing policy — RESOLVED 2026-06-22 = HYBRID
The owner chose the **hybrid**: **sensitive tasks (finance / health / journal / memory) reason on a LOCAL model and never leave the box; everything else routes to Codex/cloud.** The **sensitivity router** (existing) gates what is allowed to leave. **The privacy wall is KEPT** — ADR-003/005/006, the **M2** security wall, the local sensitive-reasoner (27B prod / 8B dev), the recovery-passphrase + passkey unlock, and the local-model host (Mac/MLX prod) **all stay in force; nothing is retired.** The net change vs the original local-first design is **additive**: non-sensitive reasoning moves to the Codex subscription.

## Refinement 2026-06-22 — sensitivity gate = local model (not regex) · sensitive reasoner = Codex-distilled · phased

A follow-on design pass (owner + planning) pressure-tested the hybrid's two soft spots — *how* sensitivity is decided, and *how good* the local sensitive path can be — and locked an upgraded version. **An earlier same-day idea, "scope sensitive data out of Artemis entirely" (drop the classifier + local reasoner + most of M2; cloud-everything is then clean), was considered and REJECTED:** scoping-out is too blunt (esp. for *incidentally*-sensitive email) and gives up sensitive assistance. The hybrid is **kept and improved** instead.

**1 — Sensitivity gate = a cheap LOCAL model, run at INGESTION (replaces the regex).** The blocked `brain-sensitivity-routing` posture question is **RESOLVED → option C (local-classifier-first).** A regex egress-gate is rejected as the primary mechanism (the standing apex-security BLOCK: a regex can't be complete; a false-negative leaks unrecoverably). A small local instruct model (4B-class; fits the RTX 5060 Ti 8 GB dev box, trivial on the Mac) classifies sensitivity by *reading the content **on-box*** — content-level precision with **no cloud round-trip**, robust to the indirect phrasing a regex misses. Posture: **fail-closed** (unsure → sensitive), matching the owner-rules "precision-first / needs-review when unsure" stance. **Clean seam: gate at ingestion** (email/documents entering the corpus), not every turn — sensitive content never enters the cloud-visible corpus, so later cloud queries are auto-safe; the owner's own typed prompt is the one remaining outbound path, guarded separately.

**2 — Sensitive reasoner = Codex-distilled (not a base small model).** The local sensitive reasoner's capability gap vs Codex is closed via **reasoning distillation** (reuses `distill-datagen-pipeline`): Codex (teacher) generates high-quality reasoning traces on **synthetic / generic** finance-health-journal scenarios → fine-tune the local model → the trained local model applies the learned capability to the owner's **real** data on-box. **Hard guardrail: the teacher trains on SYNTHETIC data only — the owner's real records never reach the cloud.** The teacher seam stays pluggable (Claude *or* Codex). Eyes-open: a distilled 4B is still a 4B (strong on narrow, recurring tasks; a residual gap on open-ended reasoning); the fine-tuning back-half is hardware-gated (Mac / GPU-box; the deferred MLX-training step + its known bug).

**3 — Phasing (additive — same gate + ingestion seam in both phases).**
- **Now (pre-Mac):** local-model gate at ingestion → **detect-and-drop** (sensitive kept out of cloud; base-local handling only) + **start the Codex-teacher distill drip** generating sensitive-domain traces.
- **Later (Mac + training):** the distilled local reasoner **graduates into** the `sensitive_reasoner` role → full **detect-and-route-local** sensitive assistance.

**Effect on specs:** `brain-sensitivity-routing` is **unblocked but its regex mechanism is SUPERSEDED** — it must be re-drafted to a local-model gate at the ingestion seam (regex → model; the `sensitivity.py` content changes). `distill-datagen-pipeline` gains sensitive-domain reasoning categories + the pluggable Codex teacher. `composite-model-routing` / `codex-model-adapter` are unaffected.

## Refinement 2026-06-23 — architecture-validation reservations (H: fallback ladder + recipe-quality gate · model-residency budget)
Closes the architecture-validation research's two model-layer foundational calls (`docs/research/2026-06-23-architecture-validation/03-holistic-end-state.md` Q5.4 + the portfolio-fit / 64GB lever). All behind the existing `ModelPort` seam — additive.

**H1 — cloud-reasoner fallback LADDER (non-sensitive path only).** The pluggable seam's degrade path is made explicit and structural (not just a quota guard). Sensitive reasoning **never** escalates to cloud (the ADR-022 wall holds); the ladder governs only the non-sensitive surface:
- **Rung 1 (primary)** = **Codex gpt-5.5** (ChatGPT subscription).
- **Rung 2 (alt-cloud)** = **DeepSeek Pro API** — pay-per-token (API, *not* a subscription/CLI → dodges the OAuth/undocumented-backend fragility), vendor diversity; only ever sees non-sensitive data.
- **Rung 3 (local)** = a local **Qwen3-Instruct** model — the **documented default** (snappy, instruction-tuned, fits the reactive reasoner role), **hardware-tiered** (~8B on the RTX 5060 Ti dev box → ~32B-class on the 64GB Mac). The final **Instruct-vs-reasoning-distilled checkpoint** (Qwen3-Instruct vs DeepSeek-R1-Distill-Qwen) is **benchmark-confirmed at Mac bring-up** — both share the same Qwen runtime, so it is a reversible checkpoint swap behind the port, not a structural fork.
- Keep `ModelPort` provider-agnostic so more rungs can be added; `roles.toml` maps the ladder.

**H2 — recipe-quality gate + re-seed path.** Recipe quality is *baked in from the teacher at seeding time*, so a degraded/unavailable teacher during the bootstrap window would permanently imprint a weak local recipe library. Beyond the existing replay-verify + recurrence gate, add a **teacher-quality-aware gate** before a distilled recipe is promoted, and a **refresh/re-seed path** to re-author recipes that were seeded under a weak teacher once a stronger one is available. (Lands in M7-b promotion policy + `distill-datagen-pipeline`.)

**Model-residency / load-evict budget (portfolio fit · reaffirms 64GB).** The whole local-model portfolio (reasoner + embeddings + reranker + visual + STT/TTS/speaker-ID) must co-exist on one box; the voice models are negligible (Parakeet 0.6B + Kokoro 82M + Sortformer + SmartTurn ≈ <2 GB total), the memory hog is **reasoner + vision**. Decisions:
- **64GB unified memory is reaffirmed as the single highest-leverage hardware call** — it lets a 27–32B reasoner + vision + voice co-reside without an evict dance.
- Reserve a **model-residency convention + load/evict policy seam** (which models stay hot vs load-on-demand), tied to the F durable-exec / GPU-contention work (ADR-024) — the heartbeat + Task Executor + voice loop contend for the GPU. Don't build the manager now; reserve the seam.
- **Dev-box VRAM budget (RTX 5060 Ti 8 GB, Ryzen 7700, 32 GB RAM)** — estimates to verify at first load (Q4 weights ≈ 0.55 GB/1B + KV):

  | Model set | ~Footprint | On 8 GB |
  |---|---|---|
  | Always-hot (embeddings 0.6B + reranker 0.6B + VAD/EOU) | ~1.5 GB | ✅ ample headroom |
  | + reactive reasoner (Qwen3-4B Q4 +KV) | ~5 GB | ✅ fits |
  | + sensitive reasoner (Qwen3-8B Q4 +KV) | ~7.5 GB | ✅ fits, tight |
  | + vision (Qwen3-VL-4B Q4) | ~5.5 GB | ✅ fits |
  | + voice loop (Parakeet+Kokoro+Sortformer) | ~3 GB | ✅ fits; coexists w/ 4B reasoner (~6.5 GB) |
  | 8B sensitive + voice concurrent | ~9 GB | ❌ over — evict or CPU-offload |

  Read: 8 GB develops/tests **every** component and runs the ambient set + one medium model + voice together, but **cannot** hold the heavy reasoner + vision + voice all hot at once — so the dev box itself *requires* the load/evict manager (32 GB system RAM = the spill/fast-reload buffer). The dev-box constraint validates building the residency seam early rather than discovering it on the Mac.

## Consequences
- **Hybrid (chosen):** non-sensitive reasoning → Codex-subscription; **sensitive → local model** (RTX 5060 Ti 8B in dev / Mac 27B in prod). The privacy wall (M2 / ADR-003/005/006), the local sensitive-reasoner, and the recovery-passphrase/passkey unlock **all stay**; **nothing is retired**. The change is additive — a cloud path for the non-sensitive surface, gated by the sensitivity router.
- **Either way:** Windows-first build holds · Tauri client (ADR-023) holds · task executor (ADR-024) holds · proactivity = local trigger + on-demand cloud.
- **Cost:** **flat ChatGPT-subscription** by default (Codex on plan quota; Pro $100/$200 for 5×/20× headroom; no per-token bill) — the local trigger keeps usage under the caps. Fallbacks cost as usual (local = free; metered API = per-token). **Model expected usage against the 5-hour/weekly caps before committing.**

## Alternatives considered
- **Full cloud pivot incl. orchestration on a hosted harness** — *rejected*: lock-in, the third-party-harness bans, loss of control.
- **Build on Hermes / OpenClaw** — *rejected*: immature / insecure / no privacy model / provider-banned for subscription use.
- **OpenAI subscription via Codex** — *adopted as the default reasoning backend* (revised after closer research): OpenAI permits Codex on a ChatGPT plan for **personal** use, so an individual driving `codex exec`/the SDK on their own machine is allowed (the bans hit third-party *products*). Accepted with eyes-open conditions (coding-oriented · rate caps · undocumented backend) **behind a pluggable seam** with local/API fallback. *Building Artemis ON Codex as a foundation* stays rejected — it is a coding agent; Artemis **orchestrates** it as a swappable engine.
- **Keep fully local-first (the prior locked design)** — still viable, and the **fallback** if cloud cost or the privacy trade-off proves wrong.

## Parked / next
Model expected usage against the Codex subscription rate caps (+ the fallback API cost) · **owner to run `codex login` + `codex exec` end-to-end** to confirm the subscription path on their plan · the constrained-decoding × Pydantic AI integration check (on Windows/Ollama) · first-hand Hermes repo read to extract the GEPA + layered-memory specifics for the recipe system.

## Refinement 2026-06-25 — Finance sensitivity narrowed: whole-domain → content-grade

**Decided:** owner + planning, 2026-06-25. Closes the *Source.sensitivity override (HIGH privacy gap)* flagged in continuation 7.

### What changed

ADR-022 (and the FIN-d spec) previously treated **all finance content** as hard-sensitive — reasoning locally, never cloud. This posture is **narrowed**: only **access/identity-grade finance content** is hard-sensitive; **soft finance facts** (spending patterns, subscriptions, category totals, individual transactions, institution names) are **general / cloud-OK**.

| Grade | Examples | Sensitivity |
|---|---|---|
| **Access / identity** | Full card/account numbers (beyond masked last-4), credentials, OTPs, CVV | `sensitive` — hard lock |
| **Government identity** | NRIC, passport number, DOB, home address | `sensitive` — hard lock |
| **Soft finance** | "Owner pays ~$15/mo for Netflix", category totals, merchant names, account balances | `general` — cloud-OK |

The **privacy wall (ADR-003/005/006) is unchanged** — the enforcer still gates on `chunk.sensitivity` / `fact.sensitivity`; we only changed what gets tagged.

### Accepted risks

1. **Aggregation risk:** many soft facts together compose a financial profile that is more sensitive than any single fact. Accepted; the classifier must evaluate combinations, not just isolated facts, when uncertain.
2. **Classifier separation risk:** the local model classifier must reliably distinguish access-grade content from soft finance content. **Mandatory consequence: the classifier MUST fail-closed to `sensitive` when uncertain** — any ambiguous or partial access-grade signal → `sensitive` + ask-owner. This is non-negotiable.

### Effect on FIN-d

`push_finance_knowledge` in `src/artemis/modules/finance/knowledge.py` currently forces every finance fact to `sensitivity="sensitive"` (inline comment: *"A finance fact must NEVER be tagged general"*). This invariant is **amended**: derived soft facts from `derive_finance_facts` (subscriptions, recurring merchants, spending patterns) become **general** and must NOT be forced sensitive. The `force_sensitive` lever now serves journal, health, email, and access/identity-grade content — not soft finance.

The `IngestPipeline.ingest` path (via `Source`) should classify soft-finance staging files through the normal classifier rather than short-circuiting to `sensitive`. The `source_sensitivity="sensitive"` kwarg passed to `memory_queue.enqueue` inside `push_finance_knowledge` must similarly be removed or set to `None` / `"general"` for soft facts.

### Effect on Source.force_sensitive

The new `Source.force_sensitive: bool = False` field (spec: `sensitivity-ground-rules.md`) is a one-directional upgrade-only lever. Callers that set it: journal, health, and email connectors. Finance connectors do **not** set it — their content goes through the classifier, which will tag access-grade items sensitive and pass soft facts through as general.
