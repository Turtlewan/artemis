# Research: Agent-Loop Reliability — stress-testing the "Geometric Reliability Decay / Cascading State Contamination" critique

**Date:** 2026-06-16
**Confidence:** HIGH (primary sources across all three lines: reliability-engineering canon + peer-reviewed agent science)
**Re-research after:** 2026-09-16 (the classical-reliability half is stable ~1yr; the agent-science half is fast-moving ~14–90d — re-check the agent-loop numbers quarterly)
**Phase-2 agent notes:** `2026-06-16-agent-loop-reliability/agent1-classical-reliability.md` · `…/agent2-agent-error-compounding.md` · `…/agent3-self-correction.md`

## Summary
A widely-shared critique argues that looping an imperfect AI asset causes "Geometric Reliability Decay" (`R = 0.9ⁿ → 0`) leading to "Cascading State Contamination" and an inescapable "Absorption State." **The headline math is wrong (topology error) and two of the three coined terms are non-standard or inverted — but the underlying concern is real, and is in fact *better* supported by the evidence than the critic's own framing.** The correct lesson is not "don't loop" but a precise, falsifiable design rule: **a loop is safe iff its iterations are idempotent, bounded, reset to clean state, and gated by an *external/independent* verifier.** Independence — of attempts and of the verifier — is the master variable. Three separate bodies of literature converge on it.

## The verdict in one table

| Critic's claim | Holds up? | What the literature actually says |
|---|---|---|
| Retry loop reliability = `0.9ⁿ`, decays to 0 | **WRONG — topology error** | `0.9ⁿ` is the **series** formula (N *different* steps all required). A retry of the *same* step is **parallel/redundant**: `R = 1−(1−p)ⁿ`, which rises toward **1**. His own numbers describe a pipeline, not a retry. [VERIFIED] |
| "Geometric Reliability Decay" | **Coined / non-standard** | The real phenomenon (chain of distinct steps compounding downward) is just the series reliability formula — and it *is* measured in agents (below). [VERIFIED] |
| "Cascading State Contamination" | **Coined — but names a real thing** | Established terms: **cascading failure** and **metastable failure** (Bronson et al., HotOS 2021) — a self-sustaining degraded state where **retry amplification is the #1 sustaining mechanism in >50% of incidents**. [VERIFIED] |
| "Absorption State" traps the loop in chaos | **Inverts Markov theory** | In an absorbing Markov chain the **SUCCESS state is the absorbing attractor**; given any p>0 the loop converges *toward* success, P(not absorbed)→0. A self-sustaining bad equilibrium is a **metastable failure**, not an absorbing state. [VERIFIED] |
| "Looping an imperfect agent → guaranteed failure/chaos" | **Half-right: real, measured, but conditional — not a guarantee, not chaos** | Compounding is empirically confirmed; but failures are *taxonomized and structured*, domain-dependent, and mitigable. "Guarantee" and "chaos" are overstatements. [VERIFIED] |

## Key findings

### Line 1 — Classical reliability engineering (the math)
- Series (all N must pass) `R=∏pᵢ=pⁿ` decays; parallel/redundant (need ≥1 of N) `R=1−∏(1−pᵢ)=1−(1−p)ⁿ` improves toward 1. A "retry until success" loop is the **parallel** topology. `[VERIFIED — Wikipedia Reliability Block Diagram; peer-reviewed RBD literature]`
- Retries help **iff** failures are *transient*, attempts *independent*, operation *idempotent*. When the failure is persistent/structural/state-corrupting, effective per-attempt p collapses and even the correct parallel formula yields ~0 benefit. `[VERIFIED — AWS Builders' Library, "Making retries safe with idempotent APIs"]`
- **Retry amplification is real:** multi-layer retries multiply (Google SRE: 4³ = 64 DB requests from one action). Mitigations, all Tier-1: bounded retries (AWS Well-Architected REL05-BP03), exponential backoff + jitter, **circuit breaker** (Nygard, *Release It!*), **token-bucket retry budgets** (Google SRE). `[VERIFIED]`
- Non-idempotent partial-state corruption is handled by **saga / compensating transactions** (Azure Architecture Center), **transactional outbox**, and **checkpoint-and-restore** from a clean checkpoint. `[VERIFIED / COMMUNITY]`

### Line 2 — Agent science (the compounding is real and measured)
- **METR / Toby Ord (arXiv 2505.05115, 2025):** survival analysis on real agent traces shows exponential success decay with task length; Claude 3.7 Sonnet **half-life ≈ 59 min** — `success(2T)=success(T)²`. `[VERIFIED]`
- **"Six Sigma Agent" (arXiv 2601.22290, 2026):** even **99%/step → 36.6% at 100 steps**. `[VERIFIED]`
- **"Beyond pass@1" (arXiv 2603.29231, 2026):** 23,392 episodes; aggregate pass@1 **76.3% → 52.1%** as horizon grows; SWE graceful-degradation 0.90 → 0.44. `[VERIFIED]`
- **Independence rarely holds in agent loops:** a shared scratchpad/context means a failed attempt *contaminates* the next, so real compounding is **worse than `pⁿ`**. Mechanisms: **context poisoning** (error reproduced every step), "Lost in the Middle" >30% accuracy drop (Liu et al., TACL 2024), MAST failure taxonomy (arXiv 2503.13657 — top modes incl. "no/incomplete verification" 11.8%). `[VERIFIED]`
- **But not chaos:** failures are taxonomized (MAST 14 modes; Aegis 6 categories) and domain-dependent (doc-processing degrades gently; SWE collapses). `[VERIFIED]`
- **Measured mitigations:** process-reward verification gates **+10.6pp** on SWE-bench (SWE-PRM, arXiv 2509.02360); parallel consensus **5%→0.11%** error with 5 samplers; human checkpoint gates **6.7%→66.7%**; task decomposition into independently-verified atomic subtasks; context hygiene / phase-boundary state resets / subagent isolation. `[VERIFIED / COMMUNITY]`

### Line 3 — Self-correction loops (the self-judging trap — the critic's sharpest valid point)
- **Intrinsic self-correction *worsens* reasoning** (Huang et al., DeepMind, ICLR 2024, arXiv 2310.01798): GPT-4 GSM8K **95.5% → 89.0%** over two self-correction rounds; prior "gains" used oracle stop-labels (not self-correction). `[VERIFIED]`
- **Survey (Kamoi et al., TACL 2024):** *no* prior work shows successful self-correction from prompted LLM feedback alone on general reasoning. `[VERIFIED]`
- **"FlipFlop" (arXiv 2311.08596):** merely re-challenging ("Are you sure?") flips answers **46%** of the time, −17% accuracy — and every self-critique loop is structurally a chain of such challenges. `[VERIFIED]`
- **Iteration helps only with an EXTERNAL/INDEPENDENT signal:** Reflexion's 91% HumanEval comes from **unit-test results**, not self-opinion; Self-Refine excluded GSM8K (no gain) and worked on style tasks where LLM preference *is* the metric; SCoRe shows self-correction must be **RL-trained into weights**, not prompted. A verifier must be **substantially stronger** than the generator (ACL Findings 2024). `[VERIFIED]`
- **Implication:** "loop until the model says it's done" is a **zero-signal stop condition** and is unsafe. `[VERIFIED]`

## The unifying principle (synthesis)
The critic conflated three distinct loop pathologies and then mislabeled them with one wrong formula. They are real but **separable and each conditional**:
1. **Series compounding** — a chain of N distinct required steps decays as `pⁿ`. (Real; measured. Fix: decompose + verify each step → raises effective per-step p.)
2. **Broken independence / state contamination** — shared mutable state correlates attempts and can drive a metastable degraded equilibrium. (Real; the #1 incident sustainer. Fix: idempotency, clean-state reset, transactional/compensable side-effects, circuit breaker, retry budget.)
3. **Self-judged exit** — a loop that grades itself with the same imperfect asset degrades on reasoning. (Real; strongest evidence. Fix: external/independent verifier; never self-assessed "done.")

**A retry loop is therefore safe ⇔ idempotent · bounded · clean-state-per-iteration · externally/independently verified.** Independence is the master variable in all three lines. "Don't loop" is the wrong conclusion; "don't loop *naively*" is the right one.

## Artemis mapping — loop-shaped components + guardrail audit
Artemis already embodies several of the right answers; the gaps are concentrated in the agentic loops.

| Loop | Risk line(s) | Already mitigated | Check / add |
|---|---|---|---|
| **GATE action-staging** (external-effect writes) | 2 | **stage→approve→execute-once** (ADR-012) — textbook non-idempotent-loop antidote | confirm idempotency key on re-dispatch |
| **DR-c iterative deep-researcher** (untrusted web) | 2,3 | **DR-a `artemis.untrusted` quarantine** = a state-contamination boundary | hard iteration budget + per-iteration verification independent of the generator |
| **M3-c agentic multi-hop retriever** | 1,2,3 | idempotent ingest (M3-a) | hop budget + per-hop verification gate; isolate hop context (avoid "lost in the middle") |
| **M6 heartbeat tick-loop** (`pre_tick_steps`) | 2 | — | per-tick idempotency; a poisoned tick must not corrupt the next |
| **M7-a2 escalation→distill→replay + active-learning** | 1 | DeepSeek-**judge** = an independent verifier (good) | keep judge strictly independent of the student; bounded retrain cadence |
| **distill-datagen retries** | 2 | **bounded `tenacity` + drop-and-log on fail, never raise** — correct already | none |
| **APEX verify-loop / `/loop`** | 3 | **evaluator-independence** is already a named dispatch invariant | ensure retry resets to clean state, never self-passes |

**Loop-guardrail checklist** (apply to any loop-shaped spec): (a) idempotent per iteration? (b) hard iteration/retry budget + circuit-breaker exit? (c) clean-state reset vs continue-from-contaminated? (d) verification gate **independent of the actor** (not self-judged)? (e) side-effects transactional/compensable? (f) fail-safe exit that escalates to the owner (ntfy / Tier-1 HIT queue) instead of spinning?

## Recommended Artemis home
1. **Sharpen `apex-system-design`** (it already owns idempotency / circuit breakers / retries) with a "Loop & retry reliability" rule encoding the four-property safety condition + the independence principle + the loop-guardrail checklist. Durable, system-wide, applies to every future spec. **Primary recommendation.**
2. **Add an Open Question to `docs/status.md`** — a one-time loop-guardrail audit of M3-c, DR-c, M6 against the checklist (the only loops with real gaps; corpus is frozen, so this is review-then-amend-if-needed, not a rewrite).
3. *(Optional)* promote to an **ADR** only if the audit forces a cross-cutting change worth locking. Not needed up front.

## Assumptions / gaps
- Several agent-science arXiv ids are 2026-dated and fast-moving; the *direction* is robustly multi-source even where a single number may shift. Re-check quarterly.
- The Artemis loop table is from the spec corpus as summarised in `status.md`; verify exact iteration-bound/verification wording in M3-c, DR-c, M6 during the audit before asserting a gap is real.

## Sources
Full cited source tables in the three Phase-2 agent files (above). Anchors: Wikipedia Reliability Block Diagram; AWS Builders' Library + Well-Architected REL05; Google SRE Book (Ch. 22, Handling Overload); Nygard *Release It!*; Azure Architecture Center (Saga); Bronson et al. HotOS 2021 (metastable failures); METR / Ord arXiv 2505.05115; arXiv 2601.22290, 2603.29231, 2503.13657, 2603.09619; Liu et al. TACL 2024; Huang et al. arXiv 2310.01798; Kamoi et al. TACL 2024; Colombo arXiv 2311.08596; Shinn (Reflexion) arXiv 2303.11366; Madaan (Self-Refine) arXiv 2303.17651; Kumar (SCoRe) arXiv 2409.12917; SWE-PRM arXiv 2509.02360.
