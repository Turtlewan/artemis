# ADR-024 — Task Executor: a general multi-step plan→act→verify agent + task-memory

- **Status:** Accepted
- **Date:** 2026-06-22
- **Deciders:** owner + planning
- **Relates:** ADR-004 (owner-memory — **unchanged**; this adds a *separate* task-memory) · ADR-012 (GATE — the executor stages external-effect steps there) · ADR-006 (heartbeat — background tasks ride it) · ADR-021 (cross-module reactions — distinct: event-triggered vs goal-directed) · ADR-022 (model/runtime re-architecture — supplies the planner model + the local-trigger/on-demand-cloud runtime) · agent-loop-reliability research (`docs/research/2026-06-16-agent-loop-reliability.md`).

## Context
Artemis already has *special-purpose* agentic pieces — the DR deep-research loop, recipes (learned automations), and reactions (event-triggered "when X→then Y") — but **no general goal-directed multi-step executor**. The owner wants "agents that do things": give a goal ("clean up my inbox", "plan this trip") and have Artemis plan it, call tools across spokes, execute (gated), verify, and report.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Capability** | A general **Task Executor** sits beside the router. The router gains a branch: classify *"multi-step task"* → hand the goal to the executor. |
| 2 | **Loop** | `plan → for each step { internal/reversible → execute ; external-effect → stage at GATE } → verify via a read-tool → re-plan on failure → on completion: report + write learned facts to owner-memory (A.U.D.N.)`. |
| 3 | **Execution model** | **Both** — quick tasks run foreground; long tasks run **background (default)**, advanced by the heartbeat, reporting on completion or at a GATE approval. |
| 4 | **Task-memory** | A **new, durable, resumable** store (goal · plan · per-step status · intermediate results · retry counts). **Separate from ADR-004 owner-memory** — different job (in-flight job state, not facts about the owner). ADR-004 is unchanged. |
| 5 | **Reliability spine** | Built to the agent-loop-reliability verdict: **bounded · idempotent · clean-state · externally-verified**. GATE = the human-in-the-loop interrupt; verification = read-back ("did the calendar actually change"), never trusting the model's "I did it". |
| 6 | **Planner model** | Per `roles.toml` (cloud GPT-5.x on-demand, or local, per ADR-022). The executor is model-agnostic. |
| 7 | **Graduation** | A task the executor performs repeatedly **graduates into a recipe** (M7-b / M8-d-c2 promotion machinery). The executor *feeds* the learning loop rather than sitting beside it. |

## Consequences
- A **new capability milestone (M9)** — depends on the brain (M1) + GATE + spokes + memory + heartbeat, so it is **post-spoke-wave**; not buildable until those land. Its *logic* is Windows-buildable behind the seams (ADR-022).
- Adds the **task-memory** data component (plain SQLite in dev; encrypted in prod iff the privacy wall is kept — see ADR-022's flagged policy).
- Cleanly distinct from DR (research) / recipes (repeat) / reactions (event-triggered) — it fills the **goal-directed-action** gap.

## Refinement (2026-06-23, architecture-validation reservations F + G)
The architecture-validation research (`docs/research/2026-06-23-architecture-validation/03-holistic-end-state.md`) flagged two of these as **foundational** (cheap now, expensive to retrofit across ~60 specs). Both are reservations — name the seam now, the thin impl can come at M9.

- **F — durable execution is a SHARED spine, not Task-Executor-only.** Decisions 4 + 5 above define durable, resumable *task-memory*; **F generalizes that to a single shared model.** Adopt one **checkpoint-after-each-logical-step + replay/resume** model (borrowed from LangGraph's durable-execution pattern, implemented thin behind our own seam — no framework dependency) **and a shared idempotency-key convention** used by **all three** long-running surfaces: the Task Executor, the **heartbeat** (M6 — per-tick locks so overlapping ticks can't double-fire, the named 2026 failure mode), and the **recipe-runner** (M7). One convention, three consumers; OBS/GATE logs supply the audit trail. **v1 may stub the impl** but the seam + key convention are fixed now so the three surfaces don't each invent ad-hoc persistence + naïve-retry duplication. (Cross-refs added to M6-a and M7-a2.)
- **G — planner / long-horizon mode is a first-class escalation tier, not an afterthought.** Decision 1 adds a router branch to the executor; **G hardens that into a reserved, port-shaped `router → planner` escalation seam — a peer to the router, not a special case buried in it.** Extend the `Router`/`RouteDecision` so "needs a plan / multi-step / long-horizon goal" is a first-class route outcome (an `escalate`-family decision that names the planner), keeping router-first as the default for simple tasks while making the Jarvis long-horizon path a clean escalation rather than a structural retrofit. **v1 realizes the planner via this Task Executor**; the seam lets a stronger planner swap in later. (Cross-ref added to M1-b's `Router` port.)

## Alternatives considered
- **Multi-agent crew** (CrewAI/AutoGen style) — *rejected*: owner chose a single executor, not a team of role-agents.
- **Build on Hermes/OpenClaw** — *rejected* (ADR-022): immature, no privacy model, provider-banned for subscription harnesses.
- **Adopt the LangGraph runtime** — *rejected*: borrow only its **checkpoint + interrupt** patterns (task-memory = checkpoint, GATE = interrupt); its runtime is too heavy/churny for a minimal auditable executor.

## Parked (build-phase)
Exact task-memory schema · novel-task-vs-existing-recipe routing · how deep background autonomy runs before it must check in with the owner.
