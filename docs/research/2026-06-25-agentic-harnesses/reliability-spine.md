# Agentic Harness Reliability & Checkpoint/Resume Spine — Research Findings

**Date:** 2026-06-25
**Re-research after:** 2026-07-09 (OTel GenAI conventions moving fast; PRMs fast-moving; 2-week window)
**Confidence:** HIGH on patterns; MEDIUM on specific attribute names (OTel still experimental/dev status)
**Phase:** Phase-2 retrieval — CITED FINDINGS ONLY, no final recommendation

---

## Existing-Doc Kernel Summary

Source: `docs/research/2026-06-16-agent-loop-reliability.md`

The 2026-06-16 document establishes:

- **The safety invariant:** A loop is safe iff its iterations are (a) **idempotent**, (b) **bounded** (hard retry/step budget), (c) **reset to clean state** per iteration, and (d) gated by an **external/independent verifier** (never self-judged). Independence is the master variable.
- **Measured reliability decay (VERIFIED):** METR/Ord (arXiv 2505.05115) — Claude 3.7 Sonnet half-life ≈59 min; arXiv 2601.22290 — 99%/step → 36.6% at 100 steps; arXiv 2603.29231 — pass@1 drops 76.3% → 52.1% with horizon.
- **Self-correction trap (VERIFIED):** Self-judged loops degrade reasoning (Huang et al. ICLR 2024); only external signal (unit tests, RL-trained reward) confers iteration benefit.
- **Six-point loop-guardrail checklist:** (a) idempotent per iteration? (b) hard budget + circuit-breaker? (c) clean-state reset? (d) independent verification gate? (e) side-effects transactional/compensable? (f) fail-safe escalation instead of spinning?
- **Artemis gap mapping:** M3-c multi-hop retriever, DR-c deep researcher, and M6 heartbeat tick-loop were identified as needing the checklist applied; GATE action-staging and distill-datagen retries were already correct.

---

## Topic 1 — Durable Execution: Checkpoint + Interrupt + Resume

### SOTA Pattern

The industry has converged on two complementary models in 2025-2026: [VERIFIED]

**Model A — Graph-node checkpointing (LangGraph):**
Every graph node execution is snapshotted to a persistent store keyed by `thread_id`. On failure or interrupt, the runner reloads the latest checkpoint and re-enters from that node. A `Command(resume=<value>)` object re-drives the graph from the saved state without re-running prior nodes. The checkpointer is a pluggable backend: `InMemorySaver` for development, `SqliteSaver` / `PostgresSaver` for production. Human-in-the-loop is achieved via `interrupt()` calls inside nodes — the graph pauses, serialises state, and waits indefinitely. [VERIFIED — Context7 LangGraph docs, langchain.com blog]

```python
# Canonical LangGraph pause-resume pattern
from langgraph.types import Command, interrupt

def review_node(state):
    interrupt({"payload": state["draft"]})   # saves state, blocks
    return {}   # re-entered here on resume

# Resume:
graph.invoke(Command(resume={"approved": True}), config)
```

Key constraint: side-effects executed **before** `interrupt()` must be idempotent, or moved after the interrupt boundary. [COMMUNITY — zylos.ai, langgraph ref docs]

**Model B — Event-history replay (Temporal):**
Workflow history is append-only. On crash, a new worker replays the event log; completed Activity results are read from history (not re-run). Non-deterministic calls (LLM API, random, time) are recorded as Events and returned verbatim on replay, so the workflow code re-executes deterministically. `Continue-As-New` prunes history for long-running agents to prevent history bloat. [VERIFIED — temporal.io blog, callsphere.ai, nittikkin.medium.com]

Pydantic AI gained native Temporal integration in 2025: type-safe agents with automatic crash-survive and replay-based fault tolerance, no manual checkpoint logic needed. [VERIFIED — temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal]

### Best Implementer

LangGraph for graph-topology workflows with per-node granularity and HITL pauses. Temporal for long-horizon service workflows with crash-surviveability and deterministic replay. [VERIFIED]

### Borrow for Artemis's Thin Spine

**Borrow:** Thread-ID-keyed checkpoint slot (per task, not per attempt); idempotency key on every write side-effect; `interrupt()`-style agent-inbox hook at pre-designated node boundaries. Store minimal state (step index + last verified output), not full context. [COMMUNITY — zylos.ai thin-harness patterns]

**Thin-spine implementation note:** Thread IDs must be business-task–derived (deterministic), not random UUIDs, so a resumed run resolves to the same slot. Separate read-only tool calls (replay-safe) from write tool calls (require idempotency guard). [COMMUNITY — zylos.ai]

**Domain gate for Temporal:** `NEEDS-DOMAIN: temporal.io` — blocked per source discipline for direct doc fetches; temporal.io blog posts were reachable and cited above; deeper API docs were not fetched.

---

## Topic 2 — External (Non-Self-Judged) Verification of Agent Steps

### SOTA Pattern

2025-2026 has crystallised a three-tier grading framework for agent verification: [VERIFIED — rmax.ai harness engineering; Anthropic 2026 eval grader taxonomy]

| Tier | Mechanism | Properties |
|------|-----------|------------|
| **T1 — Deterministic** | Code tools: schema validation, test suite execution, mock-server state readback, linter output, diff comparison | Fast, cheap, zero variance — gold standard |
| **T2 — Model-graded** | Verifier LLM (must be substantially stronger than actor, or domain-specialised) — faithfulness, rubric scoring | Flexible; introduces variance; use only when T1 unavailable |
| **T3 — Human audit** | Sampled human review; calibrates T2 drift | Gold standard but expensive; gate for high-stakes actions |

**Key principle:** Grade side effects, not self-reports. Check the mock SMTP server log — not whether the agent claims it sent an email. [VERIFIED — rmax.ai, eval harness survey]

**Process Reward Models (PRMs) for step-level verification:** [VERIFIED]
- AgentPRM (ACM Web Conf 2026): TD-based estimation for agent step rewards.
- ThinkPRM (arXiv 2504.16828): generative PRM that produces verification chain-of-thought; achieves state-of-art with orders-of-magnitude fewer training labels than discriminative PRMs.
- SWE-RM (arXiv 2512.21919): 30B MoE (3B activated), 256k context, execution-free verifier; achieves SOTA open-source test-time scaling on SWE-Bench Verified.
- SWE-PRM (arXiv 2509.02360): process-reward gate adds +10.6pp on SWE-bench (cited in existing doc).

**Harness benchmark evidence:** TerminalBench 2.0 — score improvement from 52.8 → 66.5 achieved with **zero model changes**, driven entirely by self-verification, tracing, better retry logic, structured termination rules, and disciplined tool use. [VERIFIED — rmax.ai]

**Replayable determinism harness (arXiv 2601.15322):** "Replayable Financial Agents" — determinism-faithfulness assurance harness replays agent trajectories against deterministic environment to detect non-reproducible tool calls; separates stochastic planning from deterministic execution for auditability. [VERIFIED — arxiv abstract]

### Best Implementer

Test-as-oracle (T1) is framework-agnostic and universally applicable. For PRM-style step grading: ThinkPRM / SWE-RM are the current leaders (2026). LangGraph + ARE/Harbor sandbox for environment state readback. [COMMUNITY]

### Borrow for Artemis's Thin Spine

**Borrow:** T1 deterministic readback first for every action class (file writes → diff check; email sends → mock transport log; memory writes → readback query). T2 verifier model only where T1 is impossible (natural-language quality, ambiguous intent). Never let the actor grade its own output. Wire verifier output as the loop exit signal, not actor self-assessment. [VERIFIED]

---

## Topic 3 — Idempotency + Bounded Loops + Circuit Breakers + Token/Step Budgets

### SOTA Pattern (2025-2026)

**Three-layer enforcement stack:** [COMMUNITY — auxot.com, truefoundry.com, dev.to/thedailyagent]

```
Layer 1 — Per-call throttling:  token-bucket rate limiter; per-tool concurrency cap
Layer 2 — Pattern detection:    circuit breaker (N consecutive failures; identical-call repetition; token-velocity spike vs. rolling average)
Layer 3 — Hard budget:          absolute token ceiling + step ceiling per session; checked BEFORE each tool call, not after
```

**Circuit breaker triggers (COMMUNITY — auxot.com):**
- N consecutive runs without state progress (no-progress detection)
- N consecutive failures
- Token cost per run exceeds K× rolling average (velocity spike)
- Identical tool call repeated (loop detection)

**Budget discipline:** check budget pre-call, not post-call — an agent that checks after issuing a call can overspend by one API call. [COMMUNITY — supra-wall.com, auxot.com]

**Idempotency is prerequisite for retry correctness:** [VERIFIED — existing doc; zylos.ai; AWS Builders' Library]
- Bind every external write to a deterministic idempotency key derived from workflow state (not attempt number).
- Read-only operations are always replay-safe.
- Write operations require: idempotency key → check-then-execute (at-most-once write); compensating transaction (saga) for multi-step rollback.

**arXiv 2603.08877 (budget-constrained agentic LLM search):** quantifies accuracy/cost tradeoffs for budget-constrained agentic search; confirms that step-budget placement (early vs. late cutoff) is a significant design variable with measurable accuracy impact. [VERIFIED]

**arXiv 2512.07665 (reliable agent engineering):** argues for machine-compatible organisational principles (separation of concerns, bounded authority zones, explicit handoff contracts) at the harness level rather than prompt level. [VERIFIED]

### Best Implementer

No single framework nails all three layers. LangGraph provides step-bounded graphs via `recursion_limit`; Temporal provides workflow-level timeouts and retry policies with exponential backoff; custom circuit-breaker middleware (Nygard pattern) is still hand-rolled in most agent harnesses. [COMMUNITY]

### Borrow for Artemis's Thin Spine

**Borrow:** Hard `max_steps` and `max_tokens` constants defined at task-spec level, checked pre-call in the dispatcher. Circuit breaker as a decorator/middleware on tool calls: trip on identical-call repeat or velocity spike → escalate to agent-inbox (ntfy) rather than silent abort. Idempotency key = `sha256(task_id + step_index + tool_name + canonical_args)`. [COMMUNITY]

---

## Topic 4 — Agent Observability/Eval: OTel GenAI Conventions + Eval Harnesses

### SOTA Pattern (2025-2026)

**OTel GenAI Semantic Conventions status:** [VERIFIED — zylos.ai; opentelemetry.io context7; greptime.com]
- SIG active since April 2024; as of May 2026 conventions remain in **Development** (not Stable) status.
- Major vendors (Datadog, Honeycomb, New Relic, Google Cloud, AWS, Azure) already support them in production.
- LangChain, CrewAI, AutoGen, AG2 emit OTel-compliant spans natively or via instrumentation packages.
- **Pydantic AI** instrumentation built on OTel; integrates with Pydantic Logfire (official), Arize AX, and Agenta.

**Key gen_ai.* attributes (Context7 / OTel spec):** [VERIFIED — opentelemetry.io spec]

| Attribute | Meaning |
|-----------|---------|
| `gen_ai.system` | Provider (openai, anthropic, aws.bedrock) |
| `gen_ai.operation.name` | chat, invoke_agent, execute_tool, create_agent |
| `gen_ai.request.model` / `gen_ai.response.model` | Model IDs |
| `gen_ai.usage.input_tokens` | Prompt tokens |
| `gen_ai.usage.output_tokens` | Completion tokens |
| `gen_ai.usage.cache_read.input_tokens` | Cache-hit tokens (provider-managed cache) |
| `gen_ai.usage.cache_creation.input_tokens` | Cache-write tokens |
| `gen_ai.usage.reasoning.output_tokens` | Reasoning tokens (o-series / thinking models) |
| `gen_ai.agent.name` / `gen_ai.agent.id` | Agent identity for agent spans |
| `gen_ai.tool.name` / `gen_ai.tool.call.arguments` | Tool execution spans |
| `gen_ai.request.max_tokens` / `gen_ai.request.temperature` | Request params |
| `gen_ai.response.finish_reasons` | Stop condition |

**MCP tool call tracing:** OTel now defines `mcp.session.id`, `mcp.method.name`, `mcp.protocol.version` alongside `gen_ai.tool.name` for MCP tool spans, enabling end-to-end tracing through MCP tool calls. [VERIFIED — Context7 OTel MCP spec]

**Critical privacy constraint:** OTel spec mandates that instrumentations SHOULD NOT capture prompt/completion content by default (PII risk). Content capture requires explicit opt-in. [VERIFIED — zylos.ai; search results]

**Standard is experimental — silent attribute drop risk:** Standard OTel SDKs do not emit `gen_ai.*` namespace attributes by default; unrecognised attributes are silently dropped. Must use a gen_ai–aware instrumentation library (opentelemetry-instrumentation-anthropic, openinference-instrumentation-pydantic-ai, etc.) or explicit attribute registration. [COMMUNITY — agileleadershipdayindia.org; zylos.ai]

**Eval harness SOTA (2025-2026):** [VERIFIED — rmax.ai; deepeval.com; cameronrwolfe.substack.com; arxiv 2602.18029]

- **Sandboxed environment per trial:** wipe and re-seed environment for every eval trial; no cross-trial state contamination.
- **Deterministic seeding:** `seed: 42` + step limits for reproducibility.
- **Tool mocks:** replace real APIs with mocks to make evals cheap, fast, deterministic.
- **Multi-tier grader:** code-based (deterministic) → model-based (LLM judge, adds variance) → human audit (calibration).
- **Derive cost-per-outcome metric:** tokens attributed to successful vs. failed invocations as a functional signal, not just cost.
- **GEPA (arXiv 2507.19457, ICLR 2026 Oral):** reflective prompt evolution reads execution traces to understand *why* failures occurred (not just that they occurred), then writes better instructions. Outperforms GRPO by up to 20% with 35× fewer rollouts; +13% aggregate vs MIPROv2. `optimize_anything()` API released 2026-02-18. [VERIFIED]

**Agentic Harness Engineering (arXiv 2604.25850):** observability-driven automatic evolution of coding-agent harnesses — uses OTel traces to automatically detect harness failure modes and propose harness improvements. [VERIFIED — arxiv abstract]

### Best Implementer

OTel GenAI: Pydantic Logfire (tightest Pydantic AI integration), Arize AX (openinference instrumentation), Datadog (widest enterprise support). GEPA for automated prompt/harness evolution. DeepEval for eval harness scaffolding. [COMMUNITY]

### Borrow for Artemis's Thin Spine

**Borrow:** Instrument every LLM call with `gen_ai.*` span attributes from day one using an OTel-aware SDK layer (not raw OTel without the gen_ai plugin — silent drops). Derive a `tokens_per_successful_outcome` metric as the primary cost-efficiency signal. Emit `gen_ai.agent.name` and `gen_ai.operation.name` on every agent span; emit `gen_ai.tool.name` + `mcp.session.id` on every MCP tool call. Content capture: opt-in only, redact before shipping off-device (local-first privacy constraint). For evals: sandboxed environment, mock tools, deterministic seed, T1 grader first. [COMMUNITY / VERIFIED]

---

## Topic 5 — Reliability Decay in Long Agent Loops: Current Evidence and Mitigations

### SOTA Evidence (2025-2026)

**Compounding confirmed across multiple 2026 papers (VERIFIED):**

- arXiv 2603.29231 ("Beyond pass@1"): 23,392 episodes; pass@1 drops 76.3% → 52.1% as horizon grows; SWE graceful-degradation 0.90 → 0.44. Formalises Reliability Decay Curve (RDC), Variance Amplification Factor (VAF), Graceful Degradation Score (GDS), Meltdown Onset Point (MOP). [VERIFIED]
- arXiv 2505.05115 (METR/Ord): Claude 3.7 Sonnet success half-life ≈59 min on real agent traces. [VERIFIED]
- arXiv 2601.22290 ("Six Sigma Agent"): even 99%/step → 36.6% at 100 steps. [VERIFIED]
- **Documented extreme case (2025):** agent executed 847 reasoning steps at $47/min without delivering a final answer; an endless refinement loop. [COMMUNITY — tosea.ai; loop engineering guide]
- arXiv 2509.25370 (MAST taxonomy — cited in existing doc): single root-cause errors propagate through subsequent decisions; Agent-Debug framework improves recovery ~25%. [VERIFIED]

**Meltdown Onset Point (MOP):** the formalised threshold at which compounding transitions from graceful degradation to catastrophic failure — domain-dependent; doc-processing degrades gently, SWE/code agents collapse. [VERIFIED — arXiv 2603.29231]

**New mechanism identified (2026) — context engineering as primary mitigation:** Anthropic formalised "context engineering" in September 2025 — curating and maintaining the optimal set of tokens in context at inference time. Context bloat (accumulated failed attempts, verbose tool outputs, duplicate reasoning) accelerates decay. [COMMUNITY — tosea.ai; arXiv 2603.29231]

**Mitigations with measured effect (VERIFIED):**

| Mitigation | Measured Gain | Source |
|------------|---------------|--------|
| Process-reward verification gate | +10.6pp SWE-bench | SWE-PRM arXiv 2509.02360 |
| Parallel consensus (5 samplers) | 5% → 0.11% error | Existing doc |
| Human checkpoint gate | 6.7% → 66.7% success | Existing doc |
| Phase-boundary context reset | Prevents "Lost in the Middle" | Liu et al. TACL 2024 |
| Harness improvements (verify + retry + trace) | 52.8 → 66.5 TerminalBench 2.0 | rmax.ai |
| Task decomposition + per-subtask verify | Raises effective per-step p | Multiple sources |
| Agent-Debug root-cause taxonomy | ~25% recovery improvement | arXiv 2509.25370 |

**"Loop engineering" as 2026 term:** the practice of designing the execution loop around the model (iteration budgets, structured termination, context hygiene, debounce for success detection) is now the dominant framing, superseding "prompt engineering" for reliability work. [COMMUNITY — tosea.ai]

**Debounce for success detection:** clear SUCCESS state definition with debounce logic (require N consecutive successful observations before accepting terminal state) prevents premature exit and false success. [COMMUNITY — tosea.ai]

### Best Implementer

No single framework fully addresses all decay mechanisms. LangGraph's per-node checkpoint + `recursion_limit` provides mechanical bounds; Temporal's replay prevents crash-induced context loss; GEPA/harness-evolution (arXiv 2604.25850) addresses prompt-level decay automatically from traces. [COMMUNITY]

### Borrow for Artemis's Thin Spine

**Borrow:** Mandatory phase-boundary context reset between agent phases (do not carry accumulated failed-attempt context into next phase). Define explicit MOP thresholds per task type (code tasks vs. document tasks have different decay profiles). Debounce success: require 1 independent verification pass, not actor self-report. Hard step budget enforced at dispatcher layer, not prompt layer. [COMMUNITY / VERIFIED]

---

## Cross-Cutting Takeaways for Artemis's Thin Spine

1. **Thread-keyed checkpoint slot is the minimum viable durability primitive.** Even without Temporal, a `thread_id → (step_index, last_verified_output)` row in SQLite gives crash-resume and HITL pause at low complexity cost. Idempotency key on writes is prerequisite.

2. **Independence is still the master variable.** Every claim from Topic 2 reinforces the 2026-06-16 finding: the verifier must be structurally separate from the actor. T1 deterministic readback (mock server log, schema check, diff) should be the first line, not a secondary measure.

3. **OTel gen_ai.* is the right telemetry bet, but requires an instrumentation plugin — not raw OTel.** The conventions are stable enough that Datadog/Honeycomb/New Relic have committed to them; Pydantic AI already emits them via Logfire. The risk is silent attribute drops without the plugin layer. MCP spans are now covered by `mcp.session.id` + `gen_ai.tool.name`. Content capture must be opt-in (local-first privacy).

4. **Three-layer budget enforcement is necessary, not optional, and must check pre-call.** Token budget + step limit + circuit breaker (velocity spike + identical-call repeat + N-failure) form a mechanical reliability floor that does not depend on model quality. Post-call checking allows overspend by one call.

5. **Context engineering at phase boundaries is the highest-leverage long-horizon mitigation.** Carrying accumulated failure context across phases is a primary decay amplifier; a clean-state reset between pipeline phases (plan → act → verify) is the single cheapest intervention with the widest measured impact.

---

## NEEDS-DOMAIN Hosts

- `temporal.io` — direct API doc pages blocked; blog pages reachable (cited above). Need `temporal.io/docs` for Temporal worker replay API specifics and `Continue-As-New` exact signature.
- `github.com` — blocked per source discipline; would contain `awesome-harness-engineering` list and `pydantic/pydantic-ai` source.
- `arxiv.org` — PDFs accessed via abstract search; full paper content not fetched.

---

## Sources

### Tier 1 — Context7 (Official Docs)
- LangGraph Python docs (context7 `/websites/langchain_oss_python_langgraph`) — checkpointer, interrupt, Command/resume patterns
- OpenTelemetry spec (context7 `/websites/opentelemetry_io`) — gen_ai.* attribute schema, MCP span attributes

### Tier 2 — Web Search / Authorized Fetches
- https://temporal.io/blog/ai-reliability-is-a-decade-old-problem — durable execution checkpoint/resume for AI agents
- https://zylos.ai/research/2026-03-04-ai-agent-workflow-checkpointing-resumability/ — thin harness checkpoint patterns
- https://zylos.ai/research/2026-02-28-opentelemetry-ai-agent-observability — OTel GenAI conventions status + attributes
- https://rmax.ai/notes/harness-new-model-agent-systems-2026/ — harness engineering as reliability lever; TerminalBench evidence
- https://dev.to/apssouza22/building-a-production-ready-ai-agent-harness-2570 — production harness architecture
- https://temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal — Pydantic AI + Temporal integration
- https://auxot.com/blog/agent-cost-circuit-breakers — circuit breaker patterns
- https://www.truefoundry.com/blog/rate-limiting-ai-agents-preventing-llm-api-exhaustion — three-layer enforcement
- https://tosea.ai/blog/loop-engineering-ai-agents-complete-guide-2026 — loop engineering; decay evidence; debounce
- https://nittikkin.medium.com/agent-workflows-are-rediscovering-durable-execution-be110661ed8c — Temporal/LangGraph adoption
- https://callsphere.ai/blog/temporal-ai-agent-workflows-durable-execution-workflow-as-code — Temporal patterns
- https://www.langchain.com/blog/making-it-easier-to-build-human-in-the-loop-agents-with-interrupt — LangGraph interrupt API

### Tier 2 — arXiv (verified abstracts / HTML)
- arXiv 2603.29231 ("Beyond pass@1") — RDC, VAF, GDS, MOP formalisation; pass@1 decay numbers
- arXiv 2505.05115 (METR/Ord) — half-life ≈59 min
- arXiv 2601.22290 ("Six Sigma Agent") — 99%/step → 36.6% at 100 steps
- arXiv 2509.25370 — MAST failure taxonomy; Agent-Debug +25% recovery
- arXiv 2601.15322 — Replayable Financial Agents determinism-faithfulness harness
- arXiv 2604.25850 — Agentic Harness Engineering; observability-driven automatic evolution
- arXiv 2602.18029 — standardised AI evaluation; models to agents
- arXiv 2507.19457 — GEPA; ICLR 2026 Oral; +13% vs MIPROv2, 35× fewer rollouts
- arXiv 2504.16828 — ThinkPRM; generative PRM with verification CoT
- arXiv 2512.21919 — SWE-RM; 30B MoE execution-free verifier
- arXiv 2509.02360 — SWE-PRM; +10.6pp SWE-bench via process-reward gate
- arXiv 2603.08877 — budget-constrained agentic LLM search; step-budget placement effects
- arXiv 2512.07665 — reliable agent engineering; machine-compatible organisational principles
