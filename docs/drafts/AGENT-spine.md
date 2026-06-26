---
spec: AGENT-spine
status: draft
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: AGENT-spine — plan→act→verify executor loop + reliability spine

**Identity:** The single agentic engine (ADR-031 A): a `plan→act→verify` loop driving steps through
the ToolRegistry, gated by `AuthorityGate`, checkpointed for resume, escalating to the inbox — with
the ADR-031 F reliability spine (external-verify-only, phase-boundary context reset, pre-call budgets
+ circuit-breaker). Pydantic AI is the LLM primitive (ADR-022/031 D).
<!-- → why: docs/technical/adr/ADR-031-...md (A unified runtime, F reliability, D engine) + docs/drafts/AGENT-engine-design.md (seam #1). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- `Task`/`Plan`/`PlanStep`/`StepResult`/`ExecutorState` come from `artemis.agentic.types`; `CheckpointStore`, `OwnerInbox`, `AuthorityGate` are injected (Prerequisites: AGENT-types, -checkpoint, -inbox, -authority). The spine constructs none of them — it composes injected seams. → impact: Stop.
- Steps dispatch through the existing `ToolRegistry` (`src/artemis/registry/`) exactly like reactions/modules — verify the `get_tool(ref)` + `callable_ref`/`args_schema` shape (ADR-016 async dispatch) and reuse it. → impact: Stop (a parallel dispatch path duplicates the tool surface).
- `pydantic-ai` is a NEW dependency (the planner LLM primitive). Add it to an optional `[agentic]` dependency group (keep the dev base lean; mirror the docling-extra precedent). Verify the current package name (`pydantic-ai`) + a maintained version at build time (typosquat/maintenance check). → impact: Stop (new dep — must be gate-verified).
- Verification is DETERMINISTIC read-back, never model self-judgement (ADR-031 F): `PlanStep.verify` is a check id resolved to a deterministic predicate (file exists / exit 0 / expected output / a registered verifier). The model's "it worked" is never accepted. → impact: Stop (self-judgement is the exact failure F forbids).
- Phase-boundary context reset: failed-attempt context is NOT carried across plan/act/verify boundaries (ADR-031 F). The loop reconstructs minimal context per phase from checkpointed state, not from accumulated transcript. → impact: Stop (carrying failure context is the measured context-decay failure).
- Budgets are pre-call: `Task.token_budget`/`step_budget` checked before each model/step call; a no-progress detector (e.g. N consecutive unverified steps) trips a circuit-breaker → escalate via `OwnerInbox.ask`, never silent abort. → impact: Stop.
- The planner model is the strong/local-routed model per ADR-022 (injected `ModelPort`-like seam or a Pydantic AI agent configured by the caller); the spine does not hardcode a provider. The coder backend (OpenHands/LiteLLM) is AGENT-coder, not here. → impact: Caution.
- Headless: kick-off is a function/CLI call (`run(task)`); progress is observable via the checkpoint + a `list`/status read; no client UI (Refinement (a)). → impact: Low.

Simplicity check: considered using a heavier agent framework runtime — rejected (ADR-022/031 D): own thin spine + Pydantic AI primitive + borrowed checkpoint/interrupt pattern, no framework runtime dependency. The loop is intentionally small; reliability is the value, not abstraction.

## Prerequisites
- Specs that must be complete first: **AGENT-types**, **AGENT-checkpoint**, **AGENT-inbox**, **AGENT-authority** (Wave-1 seams the loop composes).
- Environment setup required: add `pydantic-ai` to the `[agentic]` optional dependency group (`uv add --optional agentic pydantic-ai` or pyproject edit + `uv lock`).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `pyproject.toml` | modify | Add `[project.optional-dependencies] agentic = ["pydantic-ai>=…"]` (verified version). |
| `src/artemis/agentic/reliability.py` | create | budget tracker + circuit-breaker + deterministic-verify resolver. |
| `src/artemis/agentic/executor.py` | create | `Executor` with `run(task)`; the plan→act→verify loop composing checkpoint/inbox/authority/registry. |
| `tests/test_agent_executor.py` | create | happy path, verify-fail re-plan, budget/circuit-breaker→inbox, authority-gated step, resume-from-checkpoint, no-self-judgement. |

## Exact changes (loop shape — `executor.py`)
- `Executor(*, planner, registry, checkpoint, inbox, authority, workspace_root)`.
- `async def run(task: Task) -> TaskResult`:
  1. **PLAN** — `plan = await self._plan(task)` (planner → `Plan`); `checkpoint.save(task.id, PLANNING→ACTING, plan, 0, None)`.
  2. For each `step` from `step_index`:
     - **budget** — `reliability.check(task, steps_done, tokens_used)`; on breach → `await inbox.ask("budget/no-progress: continue?")`; `None`/"no" → `FAILED`, checkpoint, return.
     - **authorize** — `decision = authority.authorize(step, workspace_root=…)` (seam aligned: takes the `PlanStep`); if `not decision.auto` → `await inbox.ask(...)` referencing `decision.pending`; on owner approval (via staging) `authority.graduate(decision.pending.id)` + proceed, else park (`WAITING_OWNER`, checkpoint, return). A `decision.error` (e.g. stage failed) → park, never proceed (fail-closed).
     - **ACT** — dispatch `step.tool_ref` via `registry.get_tool(...).callable_ref(validated_args)` (ADR-016 await).
     - **VERIFY** — `verified = reliability.verify(step.verify, result)` (deterministic read-back); record `StepResult`.
     - **checkpoint** — `checkpoint.save(task.id, VERIFYING, plan, step_index+1, result_output)`.
     - on `not verified` → bounded re-plan/retry with **phase-boundary context reset** (drop failed-attempt transcript; reconstruct from checkpoint); exhaust retries → circuit-breaker → inbox.
  3. all steps verified → `DONE`, checkpoint, return `TaskResult(ok=True, ...)`.
- `resume(task_id)` = `checkpoint.load` → continue the loop from `step_index`.
- `reliability.py`: `BudgetTracker` (token/step ceilings, pre-call check), `CircuitBreaker` (no-progress trip), `verify(check_id, result) -> bool` (deterministic resolver: `exists:<path>` / `exit0` / `equals:<expected>` / a registered predicate — extensible, NEVER an LLM call).

## Tasks
- [ ] Task 1: Add `pydantic-ai` to the `[agentic]` optional dependency group + lock. — files: `pyproject.toml` — done when: `uv sync --extra agentic` resolves; base `uv sync` still lean; package name/version typosquat+maintenance verified.
- [ ] Task 2: Implement `reliability.py` (BudgetTracker, CircuitBreaker, deterministic `verify`). — files: `src/artemis/agentic/reliability.py` — done when: budget breach is detected pre-call; the no-progress detector trips after N unverified steps; `verify` resolves the deterministic check ids and contains NO model call; `uv run mypy` clean.
- [ ] Task 3: Implement `Executor.run`/`resume` (the loop composing checkpoint/inbox/authority/registry per Exact changes). — files: `src/artemis/agentic/executor.py` — done when: a happy-path task plans→acts→verifies→DONE with a checkpoint per step; an unverified step triggers bounded re-plan with context reset; an authority-gated step parks until approval; a budget/circuit-breaker breach escalates to the inbox (never silent); `resume` continues from the checkpoint; verification never calls the model.
- [ ] Task 4: Tests. — files: `tests/test_agent_executor.py` — done when: happy-path, verify-fail-replan, authority-gated-park-then-approve, budget→inbox, circuit-breaker→inbox, resume-from-checkpoint, and no-self-judgement (a fake "model says ok" but failing deterministic check → not DONE) all pass under `uv run pytest -q`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3] | Wave 4: [Task 4]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/reliability.py`, `src/artemis/agentic/executor.py`, `tests/test_agent_executor.py` |
| Modify | `pyproject.toml` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add --optional agentic pydantic-ai` (or pyproject edit + `uv lock`) | Add the planner primitive to the optional group. |
| `uv sync --extra agentic` | Install the agentic extra for build/test. |
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The four files above, by name (incl. `uv.lock`). |
| `git commit` | "feat: AGENT-spine plan→act→verify executor + reliability spine (ADR-031 A/F)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| Package index | `uv` resolves `pydantic-ai` into the `[agentic]` extra (one-time install). |

## Specialist Context
### Security
`cross_model_review: true` — the engine that will (later) drive host actions. Reviewer confirms: (1) every step passes through `AuthorityGate` before ACT (no ungated dispatch path); (2) verification is deterministic read-back only — a model claiming success cannot mark a step DONE; (3) budget/circuit-breaker breaches escalate to the owner inbox, never silently abort or silently continue; (4) parked/blocked tasks checkpoint and stop (no auto-proceed); (5) the new `pydantic-ai` dep is name/maintenance-verified and isolated to the `[agentic]` extra.

### Performance
(none beyond the budgets the spec enforces — GPU/RAM residency is the scarce resource, managed by the budget ceilings.)

### Accessibility
(none — headless.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/executor.py`, `reliability.py` | Docstrings: the loop contract, external-verify-only, phase-boundary reset, budget/breaker→inbox. |
| Overview | docs/technical/architecture/overview.md | Add the agentic executor to Capabilities (current truth) on archive. |
| ADR | (none) | ADR-031 records the design. |

## Acceptance Criteria
- [ ] Happy path → verify: a task with all-verifiable steps reaches `DONE` with a checkpoint saved per step.
- [ ] External verification only → verify: a step whose deterministic check fails is NOT marked DONE even if the (fake) model reports success.
- [ ] Phase-boundary reset → verify: a failed step's transcript is not carried into the re-plan (assert the planner input excludes prior failure detail).
- [ ] Authority gate → verify: a boundary-crossing step parks (`WAITING_OWNER`) until approval, then proceeds; an in-sandbox step runs without parking.
- [ ] Budget / circuit-breaker → verify: exceeding token/step budget or tripping the no-progress detector escalates via `inbox.ask` (never silent abort).
- [ ] Resume → verify: `resume(task_id)` continues from the checkpointed `step_index`.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
