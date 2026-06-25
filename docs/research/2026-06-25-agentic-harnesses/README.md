# Research synthesis: Agentic harnesses for Artemis (build-vs-borrow)

**Date:** 2026-06-25
**Confidence:** HIGH where Tier-1/primary; MEDIUM where community-only (tagged inline)
**Re-research after:** 2026-07-09 (AI/LLM tooling, 14-day clock)
**Method:** apex-research three-phase — 5 parallel Sonnet retrieval agents (per-cluster files in this dir) → Opus synthesis. Per-claim tier tags live in the cluster files.

## Summary

No single framework should be adopted wholesale — every all-in-one either pulls Artemis toward a cloud it can't use (OpenAI Agents SDK, Google ADK, Devin, Cursor, Jules, CrewAI cloud guardrails) or is a heavy platform that fights the "own thin spine" goal (Letta, AutoGen). **The survey strongly validates ADR-022: build a thin own spine, and borrow specific layers.** The recommendation is a **composition** — Pydantic AI as the agent primitive, a borrowed checkpoint/interrupt pattern for durability, GEPA for self-improvement, and for host computer-use a *gated tool stack* (vision-action loop + browser-scope + microVM code-exec) sitting under Artemis's own approval GATE. The two genuine open forks are (1) the one-shot coding executor (keep Codex CLI vs adopt OpenHands SDK) and (2) the host vision-loop privacy tradeoff.

## The layered recommendation (what to build vs borrow)

| Layer | Decision | Pick | Why |
|---|---|---|---|
| **Agent primitive** | BORROW | **Pydantic AI** | Local-first (`Agent('ollama:…')`), typed, MCP-native, smallest surface; ADR-022 confirmed. [VERIFIED] |
| **Durability / checkpoint / interrupt** | BORROW PATTERN (not runtime) | **LangGraph + LlamaIndex Workflows patterns** | `interrupt()`/`Command(resume=)` + `WorkflowCheckpointer.run_from()`. Min-viable = thread-keyed SQLite row + idempotency keys. Temporal/Restate if heavier (Pydantic AI has native Temporal). [VERIFIED] |
| **Reliability spine** | BUILD (borrow patterns) | own dispatcher | independence/external-verification = master variable; T1 deterministic readback before T2 model-grade; 3-layer pre-call budget (token-bucket→circuit-breaker→hard cap); **phase-boundary context reset** = highest-leverage anti-decay. [VERIFIED/COMMUNITY] |
| **Observability** | BORROW | **OTel `gen_ai.*` via Pydantic + Logfire** | Conventions still "Development" but production-adopted; needs a gen_ai instrumentation plugin (raw OTel silently drops the attrs); content-capture opt-in for local-first. [VERIFIED] |
| **Self-improvement** | BORROW standalone | **GEPA** (`dspy.GEPA`, MIT) | Reflective prompt evolution; Hermes pattern (traces→Signature→GEPA→PR→review). Spike: can a local 70B be the `reflection_lm`? else cloud-for-reflection-only (offline/async, not in sensitive path). [VERIFIED] |
| **Host computer-use** | BORROW + COMPOSE under Artemis GATE | **Anthropic CU loop ∥ browser-use ∥ E2B/Lima microVM** | No tool bounds host blast-radius alone; compose by scope. Artemis's approval gate is the reversibility governor above all three. [VERIFIED] |
| **One-shot build executor** | **OPEN FORK** | Codex CLI *(status quo)* vs **OpenHands SDK** *(local-first upgrade)* | See fork below. |

## Host computer-use — the composition (your top-priority lens)

No framework closes the blast-radius problem on a real Mac host. The synthesis across the host-cluster:

- **Vision-action loop** → borrow **Anthropic Computer Use**'s API loop for host GUI control; wrap with Artemis's gate + container. Caveat: screenshots egress to Anthropic cloud → privacy fork (accept egress for accuracy, or local LLaVA/Qwen-VL at a real accuracy cost).
- **Web tasks** → **browser-use + Playwright**: blast-radius confined to the browser (can't `rm -rf`), Apache-2, local-model-capable. Use for all web sub-tasks.
- **Code-exec sub-tasks** → **E2B (Firecracker microVM)** or **Lima/Docker** container: hardware-grade isolation — but acts on a *virtual Linux*, not the Mac host. Right for sandboxed code/data, wrong for native-app control.
- **Reversibility governor** → Artemis's **own approval GATE** extends the locked internal-reversible-auto / external-effect-gated boundary to host actions. This is the load-bearing safety layer; the frameworks supply mechanism, not policy.
- **macOS sandbox watch-item:** Seatbelt (`sandbox-exec`) is deprecated-but-functional today; Apple's **Containerization framework** (per-container VM, macOS 26, ~late 2026) is the upgrade path. Design the host-sandbox seam so it can swap.

## Skip list (with reason)

| Tool | Reason |
|---|---|
| OpenAI Agents SDK | Responses-API cloud lock breaks the privacy wall [HIGH] |
| Google ADK | Gemini-first + GCP-pull + weak MLX path [HIGH] |
| AutoGen / AG2 | Microsoft parked it (v0.7.5, Sep 2025); no checkpoints; conversation model misfits a build executor [HIGH] |
| CrewAI | Cloud-hosted guardrails/observability + role/goal/backstory abstraction fight thin-spine [HIGH] |
| Letta (MemGPT) | Full server platform (Docker+Postgres+pgvector), not borrowable-thin [HIGH] |
| Self-Operating-Computer | Demo-grade, PyAutoGUI unrestricted host access, no sandbox [HIGH] |
| Open Interpreter (as-is) | Safety model too weak (confirm-per-step only; Docker experimental) [HIGH] |
| Devin / Cursor BG / Jules | Cloud-mandatory, no local model path → code egress; reference patterns only [COMMUNITY] |

## The one-shot coding executor fork

The owner wants the engine to take a settled design and drive a complete build (plan→implement→verify→commit) in one pass — the APEX/Codex pattern Artemis already runs.

| Option | Pros | Cons |
|---|---|---|
| **Codex CLI** (status quo) | Already wired as APEX's primary coder; `codex exec --full-auto` is the proven loop; native MCP; 88.7% model SWE-bench [COMMUNITY] | OpenAI-API-bound → code context egresses; no local/Ollama fallback; Docker sandbox needed on Windows |
| **OpenHands SDK** (upgrade) | MIT; local model via **Ollama/vLLM** (air-gappable); Docker sandbox; native MCP; **77.6% SWE-bench Verified** (highest OSS) [COMMUNITY]; embeddable SDK v1 (Nov 2025) | No cross-session checkpoint (mid-build failure restarts); self-judge test problem unsolved by default |

**Recommendation:** treat this as a deliberate fork for the design discussion, not a silent default. If OpenAI-API egress for *non-sensitive* code is acceptable, Codex CLI is "don't touch what works." If local-first/privacy is to be hardened end-to-end, **OpenHands SDK is the upgrade path** — and its missing cross-session checkpoint is exactly the durability primitive the reliability cluster says to build anyway.

## Open forks for the design discussion (feed these into the agentic ADR)

1. **One-shot coding executor:** Codex CLI (keep) vs OpenHands SDK (local-first upgrade).
2. **Host vision-loop privacy:** accept Anthropic-cloud screenshot egress (higher accuracy) vs local multimodal LLaVA/Qwen-VL (no egress, lower accuracy).
3. **GEPA reflection model:** spike local-70B-as-`reflection_lm` on the M4 Pro vs cloud-for-reflection-only (offline/async, outside the sensitive path).

## Assumptions / gaps

- SWE-bench numbers and several license/version details are `[COMMUNITY]` — `github.com` was blocked for the retrieval agents (harness self-modification guard prevented domain pre-auth), so primary-source confirmation is partial. Re-dispatch with `github.com` + `aider.chat` + `jules.google` + `temporal.io/docs` + `rocm.docs.amd.com` authorized would harden these.
- macOS Containerization-framework timing (macOS 26) is vendor-announced, not yet shipped/validated.
- Local-70B-as-reflection-LM for GEPA is untested on the target hardware — a spike, not a verified capability.

## Sources

Per-cluster files in this directory, each with full per-claim tier tags + source URLs:
- `orchestration-core.md` — LangGraph, Pydantic AI, OpenAI Agents SDK, Claude Agent SDK, Google ADK
- `orchestration-alt.md` — AutoGen/AG2, CrewAI, smolagents, Letta, LlamaIndex, DSPy/GEPA
- `host-computer-use.md` — Anthropic CU, OpenAI Operator, Open Interpreter, browser-use, E2B, Docker/microVM, Self-Operating-Computer + sandbox SOTA
- `autonomous-coding.md` — OpenHands, SWE-agent, Devin, Aider, Cline, Codex CLI, Cursor, Jules
- `reliability-spine.md` — checkpoint/resume, external verification, budgets/circuit-breakers, OTel/eval, loop-decay evidence
- Folds in: `docs/research/2026-06-16-agent-loop-reliability.md`
