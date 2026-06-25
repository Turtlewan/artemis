# Coding harness — borrow-vs-build synthesis (Fork 1)

**Date:** 2026-06-25 | **Re-research after:** 2026-07-09
**Method:** 3 Sonnet retrieval agents (`coding-sdk-openhands.md`, `coding-sdk-oss.md`, `coding-sdk-vendor.md`) → Opus synthesis.
**Question:** what drives Artemis's agentic coding subsystem — borrow OpenHands, borrow another SDK, or build an own coder-seam? Locked already (owner, 2026-06-25): plan/code split + pluggable backend + agentic background + pause-to-ask-owner; privacy NOT a constraint for code.

## The decisive cross-cutting finding

**The "agent pauses to ask the owner a question" primitive is missing in EVERY candidate** — OpenHands (host→agent only), Aider (none), gptme (compose from hooks), mini-SWE (confirm-per-command, wrong granularity), goose (gotoHuman MCP, partial), Plandex (`--hil`, but wound down). Artemis must **build that seam regardless of what it borrows.** Therefore it is NOT a tiebreaker — decide on the *other* axes (scaffolding quality vs control/consistency).

## Candidate verdicts (against the locked properties)

| Candidate | Embeddable | Pluggable backend | Background+resume | Sandbox | MCP | Verdict |
|---|---|---|---|---|---|---|
| **OpenHands SDK** | ✅ H (typed Python SDK v1.24) | ✅ H (LiteLLM: Codex/OpenAI, Anthropic, DeepSeek✓, GLM reachable, Ollama) | ✅ H (pause/resume + cross-session) | ✅ H (Docker) | ✅ H native | **Only complete package; borrow candidate** |
| Google ADK | ✅ H | ✅ H (LiteLlm) | ✅ H | ✅ H | ✅ H | Pluggable but **no coding tools** → ≈ build-own with scaffolding |
| OpenAI Agents SDK | ✅ H | ◐ M (pluggable core, OpenAI gravity) | ✅ H | ✗ L | ✅ H | Conditional; OpenAI pull |
| Codex SDK/exec | ✅ H | ✗ L (DeepSeek needs proxy) | ◐ M | ✅ H | ✅ H | Practical OpenAI lock |
| Claude Agent SDK | ✅ H | ✗ **DISQUAL (Claude-only)** | ✅ H | ◐ M | ✅ H | Fails pluggability |
| Devin API | ◐ M | ✗ **DISQUAL (closed)** | ✅ H | ✅ H | ✅ H | Closed SaaS |
| Aider | ◐ M (unstable API) | ✅ H (architect/editor dual-model, LiteLLM) | ✗ L | ✗ L | ✗ L | **Best code-exec primitive to borrow**; not a harness |
| RA.Aid | ◐ L-M (CLI) | ✅ H (per-stage routing) | ◐ M (`--hil`) | ✗ L | ✗ L | **Best topology to absorb** (Research→Plan→Implement); not a dependency |
| gptme | ✅ H (REST + bg jobs + hooks) | ✅ H (DeepSeek/Ollama) | ◐ M (compose) | ✗ L | ✅ H | Composable; smaller community |
| goose | ◐ M (Rust core) | ✅ H (30+ providers) | ◐ M (async roadmap) | ◐ L-M | ✅ H | MCP-rich; Python-embed shallow |
| Plandex | ✗ L | ◐ M | ✅ H | ◐ M | ✗ L | **Wound down Oct 2025** — pattern only |
| mini-SWE-agent | ✅ H (clean Protocol API) | ✅ H | ◐ M | ✅ H | ✗ L | Minimal; no ask-owner, no MCP |

## Recommendation: BORROW OpenHands as the engine, OWN the layers above it

OpenHands SDK is the **only** option that is simultaneously embeddable + backend-pluggable + coding-native + sandboxed + MCP. Rebuilding its coding scaffolding (file localization, edit formats, test-loop — tuned to 72–77% SWE-bench) is the hard, valuable part and wasteful to redo. So:

- **Borrow OpenHands SDK as the embedded coder** — a black-box that receives a task brief and returns file edits, in its Docker sandbox, with the backend Artemis selects per task.
- **Artemis owns the layers above** (the differentiation + the parts every option makes you build anyway):
  - **Planner** = Claude/Opus (the locked plan/code split — sits cleanly above OpenHands, which is unopinionated here).
  - **AskOwnerTool + agent-inbox** = the missing pause-to-ask seam — Artemis builds it once (~100 LOC glue), reused across host-actions AND coding.
  - **GATE** = Artemis's ADR-029 gate; configure OpenHands' own `WAITING_FOR_CONFIRMATION` to **defer to it** (single gate, no double-prompt).
  - **Backend router** = Artemis picks Codex / DeepSeek API / GLM per task by cost/capability (LiteLLM under OpenHands).
- **Absorb RA.Aid's topology** (Research→Plan→Implement + per-stage model routing) as the orchestration pattern the planner uses to drive OpenHands. Pattern, not dependency.
- **Persistence: two layers, not two competing systems** — OpenHands `conversation_id`/file-store holds *in-build* state; Artemis's thread-keyed SQLite checkpoint holds *task-level* state (the executor's plan-of-builds). Reconcile by layering, not merging.

This is the same verdict shape as the broad survey: **thin own spine wraps a borrowed, proven engine.**

## The two costs to accept (borrow path)

1. **Gate reconciliation** — OpenHands has its own confirmation gate; must be configured to defer to Artemis's GATE so the owner sees one approval surface, not two.
2. **Persistence reconciliation** — OpenHands' file-store vs Artemis's SQLite checkpoint; resolved by the two-layer split above, but it's design work.

## The alternative (build-own coder-seam)

Build a thin dispatcher that calls `codex exec` / DeepSeek API / GLM directly, using **Aider's LiteLLM architect/editor engine** as the code-exec primitive and **RA.Aid's stage pattern** as the topology, all on Artemis's own spine. Pros: max control, one executor for host-actions + coding, native checkpoint/agent-inbox, no gate/persistence reconciliation. Cons: you rebuild and must *tune* the coding scaffolding that OpenHands already gets to tier-1 — genuinely hard, and the difference between a good and mediocre coding agent.

## Open sub-questions (if borrow OpenHands)
- Confirm GLM (Z.ai) routes cleanly via LiteLLM under OpenHands [COMMUNITY → verify].
- Docker requirement on the Mac Mini host (OpenHands sandbox) — fits, but a runtime dependency to note.
- `github.com` was blocked for the agents → license/API-surface details are `[COMMUNITY]`; authorize for a hardening pass if this decision needs firmer primary grounding.
