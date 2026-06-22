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

## Alternatives considered
- **Multi-agent crew** (CrewAI/AutoGen style) — *rejected*: owner chose a single executor, not a team of role-agents.
- **Build on Hermes/OpenClaw** — *rejected* (ADR-022): immature, no privacy model, provider-banned for subscription harnesses.
- **Adopt the LangGraph runtime** — *rejected*: borrow only its **checkpoint + interrupt** patterns (task-memory = checkpoint, GATE = interrupt); its runtime is too heavy/churny for a minimal auditable executor.

## Parked (build-phase)
Exact task-memory schema · novel-task-vs-existing-recipe routing · how deep background autonomy runs before it must check in with the owner.
