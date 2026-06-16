# Agent-Loop Reliability & Error Compounding — Research Notes
**Agent:** Phase-2 Retrieval (agent2)
**Date:** 2026-06-16
**Topic:** Does looping an imperfect AI agent mathematically guarantee failure/chaos? Evidence assessment.

---

## 1. Error Compounding / Accumulation in Multi-Step Trajectories

### The Core Mathematical Claim

The claim that end-to-end success ≈ (per-step success)^n is rooted in classical reliability engineering (Lusser's Law / serial reliability). Under the assumption of independent steps:

- 95%-per-step agent over 10 steps → 59.9% end-to-end success
- 95%-per-step agent over 20 steps → 35.8%
- 95%-per-step agent over 50 steps → 7.7%
- 90%-per-step agent over 20 steps → 12.2%
- 85%-per-step agent over 20 steps → 3.9%

Source: This compounding math appears across multiple practitioner analyses and is the underpinning of [COMMUNITY] Highland Edge "The Compound Error Problem: Why 95% Accurate AI Agents Still Fail" (https://highlandedge.com/resources/insights/compound-error-problem/) (2024) and [COMMUNITY] Towards Data Science "The Math That's Killing Your AI Agent" (https://towardsdatascience.com/the-math-thats-killing-your-ai-agent/) (2024).

Also cited by [VERIFIED] (peer-reviewed) arxiv: The Six Sigma Agent (2601.22290) states: "even 99% per-step accuracy degrades to 36.6% at 100 steps in multi-step workflows." (https://arxiv.org/abs/2601.22290, 2026)

### METR Empirical Evidence: Task Horizon and Exponential Decay

The most rigorous empirical grounding comes from METR (Model Evaluation & Threat Research):

**METR, "Measuring AI Ability to Complete Long Tasks"** (March 2025)
- Primary methodology: fit a logistic curve to agent success rate as a function of human-estimated task completion time across 170 tasks (SW engineering, cybersecurity, ML, general reasoning)
- The 50% time horizon = task duration at which success probability = 50%
- Results show exponential trend: frontier agent horizon doubles roughly every 7 months (2019–2025)
- 2024–2025 acceleration: doubling every ~4 months
- As of May 2026, best model (Claude Mythos) reaches 16-hour 50%-horizon / 3h06m 80%-horizon
[VERIFIED] https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/ (2025)

**METR Time Horizons live tracking**
[VERIFIED] https://metr.org/time-horizons/ (ongoing, updated 2026)

**Toby Ord, "Is there a half-life for the success rates of AI agents?"** (arXiv 2505.05115, May 2025)
- Models success as a constant per-unit-time hazard rate (survival analysis), yielding exponential decay
- Each agent has a "half-life": task duration at which success probability = 50%
- Claude 3.7 Sonnet measured half-life: ~59 minutes
- Implication: if success(1hr) = 50%, then success(2hr) ≈ 25%, success(4hr) ≈ 6.25%
- "If the task duration doubles, the success probability is squared."
- Builds on Kwa et al. (METR, 2025) research-engineering task suite
[VERIFIED] https://arxiv.org/abs/2505.05115 (2025)

**"Beyond pass@1: A Reliability Science Framework for Long-Horizon LLM Agents"** (arXiv 2603.29231, 2026)
- 396-task benchmark, 23,392 episodes, 10 open-source models, four duration buckets, three domains
- Key metric: Graceful Degradation Score (GDS)
- Software Engineering domain: GDS drops from 0.90 (short) → 0.44 (very-long horizon)
- Document processing: nearly flat (0.74 → 0.71) — domain matters
- Aggregate pass@1 drops from 76.3% at short horizon to 52.1% at very-long horizons
- "Reliability is a two-dimensional property shaped by task duration and domain structure"
[VERIFIED] https://arxiv.org/abs/2603.29231 (2026)

---

## 2. Context Poisoning / Context Rot / Error Snowballing

### Context Rot (Empirical)

**Chroma 2025 study (cited in Morph/LogRocket analyses):**
- Tested 18 frontier models (GPT-4.1, Claude Opus 4, Gemini 2.5, others)
- Every model exhibited degradation as context length increased at every input-length increment tested
- 2024–2025: average agentic prompt length grew 4× (1.5K → 6K tokens)
[COMMUNITY] https://www.morphllm.com/context-rot (2025)

**"Lost in the Middle" (Liu et al., Stanford/TACL 2024):**
- U-shaped accuracy curve: models attend to beginning and end of context, poorly to middle
- Multi-document QA (20 docs): accuracy dropped >30% when relevant document was in positions 5–15 vs position 1 or 20
- Effect persists even in 4K, 16K, 32K context windows
- As of 2026, no production model has fully eliminated position bias
[VERIFIED] https://www.semanticscholar.org/paper/Lost-in-the-Middle%3A-How-Language-Models-Use-Long-Liu-Lin/1733eb7792f7a43dd21f51f4d1017a1bffd217b5 (2024)

### Context Poisoning in Agent Loops

Redis Engineering, "Context Poisoning: How Bad Data Breaks Agent Reasoning":
- "An agent retrieves an outdated API endpoint, tries it, receives an error, and then repeatedly references the same bad endpoint in future attempts because it has 'learned' from its own mistake."
- Hallucination or error reproduces at every subsequent step
- In multi-agent systems: Agent A's degraded output enters Agent B's context as ground truth; Agent C inherits Agent B's conclusions; each hop can amplify the original error
[COMMUNITY] https://redis.io/blog/context-poisoning-agent-reasoning/ (2024)

**Context Engineering arxiv paper (2603.09619, 2026):**
- Taxonomizes degradation modes: context poisoning, context distraction (model relies on accumulated history over trained knowledge), context confusion (irrelevant information degrades quality)
- Cross-step context contamination: tool output from one step "contaminates" context for subsequent calls
[VERIFIED] https://arxiv.org/abs/2603.09619 (2026)

### Non-Independence of Retries (Critical Point)

From DEV Community practitioner analysis:
- "The independence assumption is a simplification: agent errors are correlated, because a model that misunderstands the task at step 2 tends to misunderstand it at step 12."
- Failed tool calls, dead-end reasoning, retry chatter, stale state remain in context window unless explicitly evicted
- Verifier independence is violated when verifier receives generator's scratchpad — it inherits the generator's assumptions
[COMMUNITY] https://dev.to/frank_brsrk/why-your-ai-agent-loses-the-plot-reasoning-decay-and-attention-loss-in-long-running-tasks-1cg8 (2025)
[COMMUNITY] https://www.mindstudio.ai/blog/verifier-pattern-multi-agent-systems-independent-review (2025)

---

## 3. Cascading Failures and Failure Mode Taxonomies in Agentic Loops

### MAST: Why Do Multi-Agent LLM Systems Fail? (Cemri et al., 2025)

**The most empirically grounded taxonomy of multi-agent failure:**
- arXiv 2503.13657, UC Berkeley + others
- Dataset: 1,642 annotated execution traces across 7 popular MAS frameworks (coding, math, generic tasks)
- Methodology: Grounded Theory analysis; inter-annotator agreement kappa = 0.88
- Identifies **14 distinct failure modes** in **3 categories**:

**Category I — Specification Issues (~41.8% of failures):**
  - Disobey task specification: 15.7%
  - Step repetition: 13.2%
  - Loss of conversation history: 8.2%
  - Unaware of termination conditions: 6.2%
  - Disobey role specification: 1.5%

**Category II — Inter-Agent Misalignment:**
  - Reasoning-action mismatch: 12.4%
  - Task derailment: 7.4%
  - Fail to ask for clarification: 6.8%
  - Information withholding: 1.9%
  - Conversation reset: 0.8%
  - Ignored other agent's input: 2.8%

**Category III — Task Verification:**
  - No or incomplete verification: 11.8%
  - Premature termination: 9.1%
  - Incorrect verification: 2.2%

- Overall system failure rates: **41% to 86.7%** on state-of-the-art MAS systems
[VERIFIED] https://arxiv.org/abs/2503.13657 (2025)

### Aegis: Taxonomy of Agent-Environment Failures (arXiv 2508.19504, 2025)

- Analyzed 142 agent traces (3,656 turns) across 5 agentic benchmarks
- Proposed 6 agent-environment failure categories:
  1. State-space navigation failure
  2. State awareness failure
  3. Tool output processing failure
  4. Domain rule violation
  5. Exploration failures
  6. Compounding errors from above
- Proposes environment-side optimizations (lookahead, explicit state-change signals)
[VERIFIED] https://arxiv.org/abs/2508.19504 (2025)

### Characterizing Faults in Agentic AI (arXiv 2603.06847, 2026)

- Comprehensive taxonomy: 37 fault categories grouped into 13 major categories
- Organized into 5 high-level dimensions corresponding to core agent autonomy capabilities
- Cascading/propagating faults identified as a distinct fault class
[VERIFIED] https://arxiv.org/abs/2603.06847 (2026)

### Galileo: 7 Agent Failure Modes (Practitioner)

Six modes unique to agents: tool misuse, context loss, goal drift, retry loops, cascading errors in multi-agent systems, and silent quality degradation.
[COMMUNITY] https://galileo.ai/blog/agent-failure-modes-guide (2024)

---

## 4. Mitigations: What the Literature Supports

### A. Process Reward Models (PRMs) — Verified Quantitative Evidence

**"When Agents go Astray: Course-Correcting SWE Agents with PRMs"** (arXiv 2509.02360, 2025)
- Introduces SWE-PRM: inference-time PRM that detects and course-corrects trajectory-level errors
- On SWE-bench Verified: closed-source PRM improves resolution from **40.0% → 50.6%** (+10.6 pp)
- Largest gains on medium and hard tasks
- Addresses redundant exploration, looping, failure to terminate
[VERIFIED] https://arxiv.org/abs/2509.02360 (2025)

**GUI-Shepherd** (arXiv 2509.23738, 2025)
- PRM trained on 52K-example dataset for long-sequence GUI tasks
- AndroidWorld benchmark: multi-turn online PPO (PRM as dense reward) → **+7.7 point** success rate improvement
- Inference-time verifier use: **+5.1 point** improvement
[VERIFIED] https://arxiv.org/html/2509.23738 (2025)

### B. Consensus / Parallel Sampling — Quantified

**Six Sigma Agent** (arXiv 2601.22290, 2026)
- Three-component architecture: atomic decomposition + micro-agent parallel sampling + consensus voting
- With 5% per-action error and 5 parallel agents: error reduced from 5% → 0.11%
- Scaling to 13 agents: achieves 3.4 DPMO (Defects Per Million Opportunities) = Six Sigma standard
- Demonstrates exponential reliability gains through decomposed execution + consensus validation
[VERIFIED] https://arxiv.org/abs/2601.22290 (2026)

### C. Human-in-the-Loop Checkpoint Gates — Measured

From ProSoftArena benchmark research (cited in MightyBot analysis, 2025):
- Human-Initiated Takeover (HIT) on harder tasks: success rate on harder tasks increased from **6.7% → 66.7%**
- Average steps decreased from 44.6 → 12.5 with targeted human intervention
- Correctional checkpoints reduce both error accumulation and token waste
[COMMUNITY] https://skywork.ai/blog/agent-vs-human-in-the-loop-2025-comparison/ (2025)

### D. Task Decomposition / Shorter Horizons

**Six Sigma Agent (ibid.)** and multiple surveys confirm:
- Decomposition into atomic subtasks breaks the (p^n) compounding chain
- Each subtask is independently verifiable before the next executes
- OmegaPRM, ReST-MCTS: divide-and-conquer + process reward for code generation (2024)
- ICE (3-LLM mutual critique loop): raised GPQA-diamond accuracy from 46.9% → 68.2% (+27 pp) through bounded iterative verification
[VERIFIED] https://arxiv.org/abs/2601.22290 (2026)
[COMMUNITY] https://www.emergentmind.com/topics/task-decomposition-strategies (2024)

### E. Context Engineering / Scratchpad Hygiene

LangChain Context Engineering Blog (2025):
- Evicting failed tool calls, dead-end branches, and stale state from context window
- Phase-boundary state resets for loops >10 steps with moderate tool output
- Subagent isolation (clean context per subtask) delivers largest savings when subtasks share minimal context
[COMMUNITY] https://blog.langchain.com/context-engineering-for-agents/ (2025)

---

## 5. Compounding Sequential Steps vs. Retrying One Step: Independence Problem

### The Key Distinction

**(a) Chain of n different required steps** — each new step depends on the output of the prior step. Success compounds downward regardless of retries. This is the dominant failure mode in production agentic systems. If step 3 produces bad output and step 4 consumes it, retrying step 4 alone cannot recover — the error is baked into the input.

**(b) Retrying one step until it works** — if attempts are truly independent, each retry gives a fresh probability p of success. For independent retries, probability of at least one success in k attempts = 1 - (1-p)^k (goes UP with k).

### Why Independence Is Rarely Clean in Agent Loops

The literature is clear that independence fails in practice:

1. **Shared scratchpad/context:** Previous failed attempts remain in the context window. The model sees its own failed reasoning and may anchor on it or rationalize around the error rather than starting fresh.
   [COMMUNITY] https://dev.to/frank_brsrk/why-your-ai-agent-loses-the-plot-reasoning-decay-and-attention-loss-in-long-running-tasks-1cg8 (2025)

2. **Correlated errors:** "A model that misunderstands the task at step 2 tends to misunderstand it at step 12." Systematic misunderstandings don't randomize across retries.

3. **Context contamination from retries:** "Failed tool calls, dead-end reasoning, retry chatter, and stale state all stay in the window unless explicitly evicted." Each retry attempt degrades subsequent attempts by adding noise.

4. **Retry loop failure mode (MAST step repetition: 13.2%):** Agent retries the same failing action repeatedly without recognizing the error, consuming tokens while making no progress. This is one of the most common documented failure modes.

5. **Verifier contamination:** Even in verification architectures, if the verifier receives the generator's scratchpad, independence is violated.
   [COMMUNITY] https://www.mindstudio.ai/blog/verifier-pattern-multi-agent-systems-independent-review (2025)

### What Bites Hardest in Practice

The MAST taxonomy (1,642 traces) shows **sequential dependency failures dominate**: specification issues (41.8%) and inter-agent misalignment combine to create failures that propagate through the entire task. By contrast, simple step-repetition loops (13.2%) are less catastrophic (they waste tokens but are detectable) than silent cascading errors where the agent confidently continues on a wrong foundation.

The METR/Ord empirical evidence (exponential decay with task duration) confirms that the chain-of-n-steps model explains observed agent performance better than a retry model: measured success rates follow the half-life/survival model rather than improving with iteration attempts.

---

## Key Sources Index

| # | Citation | Type | URL |
|---|----------|------|-----|
| 1 | METR, "Measuring AI Ability to Complete Long Tasks" (2025) | [VERIFIED] | https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/ |
| 2 | METR, Time Horizons live tracker (2025–2026) | [VERIFIED] | https://metr.org/time-horizons/ |
| 3 | Ord, "Half-Life for AI Agent Success Rates" arXiv 2505.05115 (2025) | [VERIFIED] | https://arxiv.org/abs/2505.05115 |
| 4 | Khanal et al., "Beyond pass@1" arXiv 2603.29231 (2026) | [VERIFIED] | https://arxiv.org/abs/2603.29231 |
| 5 | Cemri et al., "Why Do Multi-Agent LLM Systems Fail?" arXiv 2503.13657 (2025) | [VERIFIED] | https://arxiv.org/abs/2503.13657 |
| 6 | Aegis failure taxonomy arXiv 2508.19504 (2025) | [VERIFIED] | https://arxiv.org/abs/2508.19504 |
| 7 | "Characterizing Faults in Agentic AI" arXiv 2603.06847 (2026) | [VERIFIED] | https://arxiv.org/abs/2603.06847 |
| 8 | Gandhi et al., "When Agents go Astray: SWE-PRM" arXiv 2509.02360 (2025) | [VERIFIED] | https://arxiv.org/abs/2509.02360 |
| 9 | GUI-Shepherd arXiv 2509.23738 (2025) | [VERIFIED] | https://arxiv.org/abs/2509.23738 |
| 10 | Six Sigma Agent arXiv 2601.22290 (2026) | [VERIFIED] | https://arxiv.org/abs/2601.22290 |
| 11 | Liu et al., "Lost in the Middle" TACL 2024 | [VERIFIED] | https://www.semanticscholar.org/paper/Lost-in-the-Middle%3A-How-Language-Models-Use-Long-Liu-Lin/1733eb7792f7a43dd21f51f4d1017a1bffd217b5 |
| 12 | Context Engineering arXiv 2603.09619 (2026) | [VERIFIED] | https://arxiv.org/abs/2603.09619 |
| 13 | Highland Edge, Compound Error Problem (2024) | [COMMUNITY] | https://highlandedge.com/resources/insights/compound-error-problem/ |
| 14 | Redis, Context Poisoning blog (2024) | [COMMUNITY] | https://redis.io/blog/context-poisoning-agent-reasoning/ |
| 15 | LangChain, Context Engineering for Agents (2025) | [COMMUNITY] | https://blog.langchain.com/context-engineering-for-agents/ |
| 16 | Galileo, 7 Agent Failure Modes (2024) | [COMMUNITY] | https://galileo.ai/blog/agent-failure-modes-guide |
| 17 | Morph, Context Rot guide (2025) | [COMMUNITY] | https://www.morphllm.com/context-rot |

---

## Synthesis Notes (for Phase-1 synthesizer)

**Strength of critic's claim:** STRONG for the compounding model itself; NUANCED for "guarantees failure/chaos."

**Strongest measured evidence:**
- Toby Ord (arXiv 2505.05115): exponential decay is empirically confirmed via survival analysis on measured agent traces. Claude 3.7 Sonnet half-life = 59 min → success halves with every horizon doubling.
- METR: frontier agents succeed on 50% of tasks taking a skilled human ~hours, not days. Horizon is growing but compounding is real and measured.
- "Beyond pass@1" (2603.29231): SW engineering domain GDS 0.90 → 0.44 as horizon grows; aggregate pass@1 drops from 76.3% → 52.1%.
- MAST (2503.13657): 41–86.7% failure rate on SOTA MAS; 14 documented failure modes with quantified prevalence.

**Key nuances the critic's claim misses:**
1. The compounding formula assumes independence — in practice errors are correlated AND retries are not independent (shared context). This makes things WORSE, not better.
2. "Chaos" implies unpredictability; in practice failure modes are taxonomized and partially predictable.
3. Mitigations genuinely work: PRM verification (SWE-PRM: +10.6 pp; GUI-Shepherd: +7.7 pp); consensus sampling (Six Sigma: 5% error → 0.11%); human checkpoints (6.7% → 66.7% on hard tasks).
4. Domain matters: document processing nearly flat (GDS 0.74→0.71) vs. software engineering collapse (0.90→0.44).
5. The METR "time horizon doubling" trend shows that the practical consequence of compounding is bounded by and improving with model capability.
