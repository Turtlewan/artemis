# Artemis — Holistic End-State Architecture Validation

**Date:** 2026-06-23
**Scope:** Zoom-out validation of the *whole* Artemis system shape against 2025–2026 state-of-the-art personal-AI / agentic-assistant architectures. Skeptic's lens; structural-risk-first.
**Method:** Web research (10 searches + 2 source fetches), grounded in the locked SP0 brain design (`docs/technical/architecture/brain.md`) and the 2026-06-08 brain/AI synthesis.
**Confidence legend:** [H] high (multiple primary/consistent sources), [M] medium (trend-consistent secondary sources), [L] low / single-source or forward-looking.

> Note: `brain.md` still names DeepSeek as cloud teacher in places; per ADR-027 the live reality is **Codex (gpt-5.5) primary + Opus fallback** behind `ModelPort`. The *architectural shape* (sensitivity-routed hybrid behind a port) is identical and is what this report validates — the specific cloud vendor is a config-mapped role, not a structural commitment.

---

## Bottom-line verdict

**MOSTLY YES.** The overall shape — thin router-first brain + modular tool-spokes (RAG-for-tools) + local heartbeat proactivity + sensitivity-routed hybrid local/cloud + cryptographic privacy wall + recipe self-learning — is **convergent with, and in several places ahead of, what the best 2026 systems do.** Nothing in the current SOTA invalidates the foundation. Artemis independently arrived at four patterns the field has since standardized: tool-RAG, sensitivity-first routing, ambient/heartbeat agents, and skill-libraries-not-fine-tuning.

The "mostly" (not an unqualified yes) rests on **four structural gaps** that are cheaper to decide now than to retrofit across ~60 specs:

1. **No durable-execution spine** for the planned Task Executor — the field has hardened this into a *baseline requirement* in 2026, and it is the single most expensive thing to bolt on late.
2. **Router-first is correct as the default but is a ceiling for the Jarvis long-horizon end-state** — the planner-first path must be a first-class, port-shaped escalation, not an afterthought.
3. **Memory is designed as an internal subsystem, not a first-class addressable layer** — the 2026 consensus (and Artemis's own ports) point at memory-as-a-service; confirm the seam holds against multi-scope tagging + async-write defaults.
4. **The cloud-reasoner dependency** (Codex/Opus via subscription/CLI, not API) is a real bring-up fragility and a quality coupling for the seeding phase — known, but worth a structural fallback ladder, not just a quota guard.

Everything else is ADDITIVE (layer later).

---

## What the best 2026 systems do — and how Artemis compares

| Dimension | 2026 SOTA | Artemis | Verdict |
|---|---|---|---|
| **Shape** | Thin orchestrators favoured for single-purpose assistants; heavy frameworks (LangGraph/CrewAI) win for multi-agent/workflow systems with branching + HITL [H] | Thin custom spine, borrow primitives behind ports | **Aligned.** Correct for a single-owner assistant; risk is under-borrowing on durability (below) |
| **Tool scaling** | Tool-RAG / RAG-MCP / ToolShed now the standard answer; accuracy 13%→43%, token cost halved; providers cap ~128 in-context tools [H] | RAG-for-tools from day one (manifests indexed in vector store, retrieve a handful/turn) | **Ahead.** Artemis locked this before it was consensus |
| **Routing** | Sensitivity-based routing called "highest-ROI starting point"; PII/health/finance route to on-device regardless of cost; classifier <5ms; field moving toward *learned* routers (contextual bandits) [H] | Provenance gate + local zero-shot classifier, fail-closed to local | **Ahead / aligned.** SOTA endorses the exact design. Watch: field is moving from threshold rules → learned routers (additive) |
| **Privacy** | Spectrum from cloud-API to on-prem; sensitivity routing = compliance constraint that overrides cost/latency; PRISM (arXiv 2511.22788) does semantic-sketch privacy routing [H] | Cryptographic per-scope SQLCipher + Secure-Enclave keys; CaMeL dual-LLM data plane | **Ahead.** Cryptographic (not logical) isolation + CaMeL is stronger than most 2026 hybrid designs, which stop at a content classifier |
| **Proactivity** | "Ambient agents" (LangChain, Jan 2025) now a named category: event-driven, always-on, invisible-until-needed, agent-inbox UX [H] | Heartbeat: scheduled-tick-dominant + event injection, silent-success, ntfy, owner-gated | **Aligned, validated by name.** Gap: agent-inbox UX pattern (a reviewable queue of agent-initiated actions) is more evolved than ntfy push (additive) |
| **Self-improvement** | Skill libraries (Voyager lineage) dominant; GEPA (ICLR 2026 oral) = reflective prompt evolution, no fine-tuning; SkillSmith/SAGE/Trace2Skill distill traces→reusable skills; metacognitive learning emerging [H] | Recipes (SKILL.md-shaped), replay-verified, recurrence-gated, owner-promoted; distillation pipeline; explicitly NOT weight fine-tuning | **Aligned / ahead.** The "no fine-tuning, grow a skill library" bet is exactly where 2026 research landed (GEPA). Additive: GEPA-style reflective *optimization* of existing recipes |
| **Memory** | Memory now "first-class architectural component" separate from context; multi-scope tags (user/agent/run/app); 3-signal retrieval (semantic+BM25+entity); **async writes by default**; staleness of high-confidence facts is an *open problem*; bitemporal still rare [H] | Two-store (episodic bitemporal + semantic), AUDN write path, per-person partition, forgetting-as-rerank, async/batched | **Aligned / ahead.** Bitemporal + crypto-at-rest exceeds Mem0. Confirm: async-write-by-default and multi-scope tagging are explicit in the port |
| **Reliability** | Durable execution is now a *baseline requirement* — LangGraph, Pydantic AI, OpenAI Agents SDK all ship it; checkpoint = 60%+ less wasted work; idempotency tokens + bounded loops + external verification the named anti-patterns to avoid; heartbeats specifically flagged as needing per-tick locks/guards [H] | Task Executor planned with "durable task-memory, reliability spine"; heartbeat dedup_key | **GAP (foundational).** The intent is right but durability is *planned*, not foundational. 2026 says decide the persistence/replay model now |
| **Harness** | Borrow LangGraph persistence patterns; Pydantic AI for typed I/O; MCP "at the edges" is exactly the recommended posture (MCP ecosystem uneven, security-fragile, "MCP paradox") [H] | Own thin spine + borrow patterns + Pydantic-AI-style typing + MCP only at edges | **Sound.** MCP-at-edges is vindicated by the 2026 security critique. Don't adopt a framework wholesale |

---

## Answers to the five questions

### Q1 — Is the overall shape right for a Jarvis end-state? What do the best systems do that Artemis doesn't?

**Yes, the shape is right.** [H] For a *single-owner, privacy-walled* assistant, a thin router-first spine with tool-RAG spokes and ambient proactivity is precisely the converged 2026 pattern. Artemis is not chasing the field — on tool-RAG, sensitivity routing, ambient agents, and skill-libraries it *led* the consensus.

What the best 2026 systems have that Artemis doesn't yet:
- **Durable execution as a first-class spine** (not a planned add-on). [H, foundational]
- **A genuine planner/long-horizon mode** as a peer to the router, for multi-step autonomous goals — the literal Jarvis behaviour. Router-first handles "do X"; Jarvis needs "achieve goal G over hours/days," which is planner+executor territory. [H, foundational-ish]
- **Agent-inbox UX** — a reviewable queue/stream of agent-initiated work, richer than fire-and-forget push. [M, additive]
- **Learned routing** (contextual bandits over hand-tuned thresholds). [M, additive]
- **Computer-use fallback** for the long tail of apps with no API/MCP. [M, additive — see Q4]

### Q2 — Biggest STRUCTURAL risks (expensive to change after ~60 specs)

Ranked by cost-to-retrofit:

1. **No durable-execution model chosen up front.** [H] The 2026 lesson is unambiguous: agents "rediscovered durable execution," and checkpoint/replay is now baseline. If the Task Executor, heartbeat, and recipe-runner each invent ad-hoc persistence, you get the named failure modes (hidden state, overlapping heartbeats with no lock, naïve retry creating duplicate external effects). Picking a journal/replay-or-checkpoint model *and* an idempotency-key convention now is far cheaper than threading it through 60 specs later. **FOUNDATIONAL.**

2. **Router-first hard-codes a reactive ceiling.** [H] Router-first is the right *default* (planning overhead hurts simple tasks — confirmed by 2026 sources), but the planner-executor path "disproportionately helps on harder tasks with dependencies." If the brain's control flow assumes single-hop routing, the long-horizon Jarvis behaviour becomes a structural retrofit. Make planner-mode a port/escalation tier *now*, even if v1 stubs it. **FOUNDATIONAL.**

3. **Cloud-reasoner dependency (subscription/CLI, not API).** [H] Two coupled risks: (a) bring-up/ops fragility — OAuth login lapse, quota shared with the owner's own work, CLI subprocess as the seam; (b) quality coupling — recipe quality is *baked in* from the teacher, so a weak/unavailable teacher during seeding permanently degrades the local library. The `ModelPort` seam is the right mitigation, but the fallback *ladder* (teacher → alt-cloud → local) and a recipe-quality gate deserve to be foundational, not just a quota ceiling. **FOUNDATIONAL (the seam) / ADDITIVE (the specific vendor).**

4. **Local-model ceiling for sensitive reasoning is a hard, accepted wall.** [H] By design, sensitive judgment that no recipe covers AND the local model can't crack is unsolvable (the teacher can't see the data). This is correctly identified in `brain.md` as "the literal price of sensitive-never-leaves-the-box," with the only lever being a stronger *local* model (64GB / Studio path). Not a flaw — but the **64GB RAM decision is the upstream lever** for the entire sensitive-reasoning + local-teacher + GraphRAG story, and is the highest-leverage foundational hardware call. **FOUNDATIONAL.**

5. **MCP standardization risk is LOW because Artemis already hedged it.** [H] The 2026 MCP critique (uneven maturity, no standard enterprise auth, "structurally fragile attack surface," the "MCP paradox") *vindicates* Artemis's "internal modules = typed function calls; MCP only at the edges." This is a non-risk — keep the posture. **Not a risk (decision already correct).**

6. **Memory-layer addressability.** [M] If memory is wired as an internal subsystem rather than an addressable layer with multi-scope tags + async-write default, you may later refactor to match the 2026 memory-as-service consensus. Artemis's MemoryStore port + per-person partition largely covers this; just confirm async-write-by-default and scope tagging are in the signature. **FOUNDATIONAL (cheap to confirm now).**

### Q3 — Is "own thin spine + borrow LangGraph patterns + Pydantic AI + MCP" sound, or adopt more wholesale?

**Sound — do not adopt a framework wholesale.** [H] The 2026 framework comparisons are consistent: thin/custom wins for single-purpose assistants; LangGraph's value is its *persistence + HITL + time-travel* model, not its programming model. The correct move is exactly Artemis's: **borrow LangGraph's checkpoint/durable-execution *patterns* behind your own ports, not the framework.** Pydantic-AI-style typed I/O is endorsed (type safety + structured output is its whole reason to exist; it's deliberately stateless). MCP-at-edges is vindicated.

One sharpening: **borrow more deliberately from LangGraph's durable-execution model specifically** — it is the one area where the field's hardened pattern is more mature than Artemis's "planned reliability spine." Borrow the *concept* (persist after each logical step, replay/resume, per-step idempotency), implement it thin. Don't take the dependency; do take the design.

### Q4 — Emerging 2026 paradigm that would materially reshape this?

Three to track, none demanding a redesign:

- **Computer-use agents** (Claude Computer Use, Agent S2, OSWorld-MCP benchmark). [M] Materially relevant as a *fallback spoke* for apps with no API/MCP — the long tail Jarvis will hit. **ADDITIVE**, but design the spoke seam so a computer-use module can register like any other (it likely already can via the manifest contract). Don't build now; don't preclude.

- **Agentic / memory-as-OS framing** (Microsoft Agent Mode default, "agentic operating system," runtime-keeps-agents-alive + shared memory layer). [M] This is essentially what Artemis *is* (heartbeat runtime + memory layer + spokes). Validation, not threat. The one borrowable idea: a **persistent agent runtime that coordinates multiple concurrent agent activities on one box** — relevant when the Task Executor + heartbeat + voice loop run concurrently and contend for the GPU. **ADDITIVE** (already on the radar as GPU-contention spike).

- **Long-horizon autonomous agents** — "narrower than hype, stronger than skepticism" [M]; real for software/research tasks, gated by reliability + experience-reuse. This is the Jarvis end-state's spine and reinforces Q2.1 (durable execution) and Q2.2 (planner mode). **FOUNDATIONAL** insofar as it confirms those two calls.

- **Learned/adaptive routing** (contextual bandits replacing thresholds). [M] **ADDITIVE** — design the Router port so a learned policy can swap in for the threshold rules; the port already exists.

### Q5 — Per-finding: ADDITIVE vs FOUNDATIONAL

**FOUNDATIONAL — decide now (cheap now, expensive across 60 specs):**
1. **Durable-execution model + idempotency-key convention** for Task Executor, heartbeat, recipe-runner. (Borrow LangGraph's pattern, implement thin.)
2. **Planner/long-horizon mode as a first-class escalation tier** behind a port — peer to the router, even if v1 stubs it.
3. **64GB RAM decision** — upstream lever for local-teacher + sensitive-reasoning + GraphRAG. (Already flagged for WWDC; this confirms it as the single highest-leverage hardware call.)
4. **Cloud-reasoner fallback ladder + recipe-quality gate** — make the degrade path (teacher→alt→local) and a quality gate structural, not just a quota ceiling.
5. **Confirm MemoryStore port carries async-write-by-default + multi-scope tagging** in its signature (one-line confirmation, but structural if missed).

**ADDITIVE — layer later (port/seam already supports it):**
- Agent-inbox UX over ntfy.
- Learned (contextual-bandit) routing swapped behind the Router port.
- GEPA-style reflective optimization of existing recipes.
- Computer-use fallback spoke (register via manifest contract).
- Multi-agent concurrent-runtime coordination (GPU contention).
- 3-signal memory retrieval (semantic+BM25+entity) if not already.

**Already-correct decisions vindicated by 2026 SOTA (no action):**
- Tool-RAG / RAG-for-tools.
- Sensitivity-first routing, fail-closed to local.
- Cryptographic privacy wall + CaMeL dual-LLM.
- MCP-at-edges only.
- Skill-library / recipes, no weight fine-tuning.
- Thin spine, no wholesale framework.
- Bitemporal + crypto-at-rest memory (exceeds Mem0).

---

## Skeptic's residual doubts (flagged, not blocking)

- **Recipe quality during seeding is a permanent imprint.** If the teacher is degraded/unavailable during the bootstrapping window, the local recipe library inherits that weakness forever. The recurrence-gate + replay-verify help, but consider a *re-seed/refresh* path for recipes authored under a weak teacher. [M]
- **Heartbeat + Task Executor + voice loop concurrency on one 48–64GB box** is a real contention surface that the durable-execution + idempotency decisions (Q5.1) must account for — overlapping heartbeats without locks is the named 2026 failure mode. [H]
- **"Jarvis end-state" implies long-horizon autonomy**, which is exactly where 2026 reliability is weakest. The architecture's path there runs through Q5.1 + Q5.2; if either is deferred, the end-state is structurally gated. [M]

---

## Sources

- [10 Best Local AI Assistants 2026 — Vellum](https://www.vellum.ai/blog/best-local-ai-assistants)
- [Build Personal AI System 2026 — explainx.ai](https://www.explainx.ai/blog/build-personal-ai-system-local-workflow-2026)
- [Second Brain AI Assistant course — decodingai/GitHub](https://github.com/decodingai-magazine/second-brain-ai-assistant-course)
- [LangGraph vs OpenAI Agents SDK vs PydanticAI 2026 — open-techstack](https://open-techstack.com/blog/langgraph-vs-openai-agents-sdk-vs-pydanticai-2026/)
- [Agent framework comparison — Speakeasy](https://www.speakeasy.com/blog/ai-agent-framework-comparison)
- [Best AI Agent Frameworks 2026 — alicelabs](https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026)
- [Agentic Workflow Anti-Patterns 2026 — digitalapplied](https://www.digitalapplied.com/blog/agentic-workflow-anti-patterns-orchestration-mistakes-2026)
- [Agents at Work: 2026 Playbook — promptengineering.org](https://promptengineering.org/agents-at-work-the-2026-playbook-for-building-reliable-agentic-workflows/)
- [Building Production-Ready AI Agents 2026 — MLflow](https://mlflow.org/articles/building-production-ready-ai-agents-in-2026/)
- [Multi-Agent System Reliability — getmaxim.ai](https://www.getmaxim.ai/articles/multi-agent-system-reliability-failure-patterns-root-causes-and-production-validation-strategies/)
- [Agent Architectures: Planner/Executor/Router — Medium (V. Agarwal)](https://medium.com/@vishal.agarwal.iitk/agent-architectures-planner-executor-router-patterns-148fe54ff595)
- [AI Agent Routing Patterns — Taskade](https://www.taskade.com/blog/ai-agent-routing-patterns)
- [Ambient Agents & Agent Inbox ft. Harrison Chase — Sequoia](https://sequoiacap.com/podcast/training-data-harrison-chase-2/)
- [What's next for agentic AI: ambient agents — VentureBeat](https://venturebeat.com/ai/whats-next-for-agentic-ai-langchain-founder-looks-to-ambient-agents)
- [Self-Improving AI Agents: 2026 Guide — o-mega](https://o-mega.ai/articles/self-improving-ai-agents-the-2026-guide)
- [SkillSmith — arXiv 2606.01314](https://arxiv.org/html/2606.01314)
- [GEPA / Hermes Agent Skills guide — MACGPU](https://macgpu.com/en/blog/2026-0618-hermes-agent-skills-advanced-gepa-guide.html)
- [Hybrid Cloud-Local LLM Architecture Guide 2026 — SitePoint](https://www.sitepoint.com/hybrid-cloudlocal-llm-the-complete-architecture-guide-2026/)
- [Hybrid Cloud-Edge LLM routing — TianPan.co](https://tianpan.co/blog/2026-04-10-hybrid-cloud-edge-llm-inference-routing)
- [Privacy-Preserving Inference in Practice — TianPan.co](https://tianpan.co/blog/2026-04-20-privacy-preserving-inference-production-llm)
- [Perplexity hybrid local-cloud at Computex 2026 — VentureBeat](https://venturebeat.com/technology/perplexity-ai-unveils-hybrid-local-cloud-inference-system-at-computex-2026)
- [PRISM: Privacy-Aware Routing — arXiv 2511.22788](https://arxiv.org/pdf/2511.22788)
- [MCP Ecosystem 2026 — ChatForest](https://chatforest.com/guides/mcp-ecosystem-2026-state-of-the-standard/)
- [6 Critical Challenges Facing MCP in 2026 — Medium (M. Mochalkin)](https://medium.com/@MattLeads/6-critical-challenges-facing-the-mcp-in-2026-06258e914402)
- [Tool RAG: Next Breakthrough — Red Hat Emerging Tech](https://next.redhat.com/2025/11/26/tool-rag-the-next-breakthrough-in-scalable-ai-agents/)
- [RAG-MCP: Scaling Tool Selection — Medium](https://medium.com/@pankaj_pandey/rag-mcp-scaling-tool-selection-for-ai-agents-6de02b08b64f)
- [Toolshed / RAG-Tool Fusion — arXiv 2410.14594](https://arxiv.org/pdf/2410.14594)
- [Durable Agent Execution in Production 2026 — AgentMarketCap](https://agentmarketcap.ai/blog/2026/04/10/durable-agent-execution-production-temporal-modal-event-sourced)
- [Durable Execution in LangGraph — Vadim's blog](https://vadim.blog/durable-execution-agents-that-survive-failure-and-resume-where-they-left-off)
- [Durable execution — LangChain docs](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [Agent Workflows Rediscovering Durable Execution — Medium (Koshy)](https://nittikkin.medium.com/agent-workflows-are-rediscovering-durable-execution-be110661ed8c)
- [State of AI Agent Memory 2026 — Mem0](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Memory for Autonomous LLM Agents — arXiv 2603.07670](https://arxiv.org/html/2603.07670v1)
- [Agentic Operating System Deep Dive — Asanify](https://asanify.com/blog/news/agentic-operating-system-june-3-2026/)
- [Agent S2 (computer-use) — arXiv 2504.00906](https://arxiv.org/pdf/2504.00906)
- [Long-horizon agents in production — EPAM](https://www.epam.com/insights/ai/blogs/how-to-use-long-horizon-agents-in-production)
