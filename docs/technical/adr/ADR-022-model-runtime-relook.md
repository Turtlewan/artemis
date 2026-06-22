# ADR-022 — Model & runtime re-architecture: on-demand cloud reasoning + local-trigger proactivity + composed harness

- **Status:** **Accepted** — privacy-routing policy resolved 2026-06-22 = **hybrid** (sensitive → local, rest → Codex/cloud; the wall is kept).
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
