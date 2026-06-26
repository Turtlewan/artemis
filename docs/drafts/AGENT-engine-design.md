# Agentic engine — shared design backbone (spec-series anchor)

Coherence anchor for the dev-buildable agentic spec series (ADR-031 Phases 1–4, headless-first).
NOT a spec — the shared module layout + inter-spec seams every AGENT-* spec binds to, so the
series stays file-disjoint (ADR-029) and interlocks. Durable *why* lives in ADR-031; this pins the
*what/where*.

## Module layout — `src/artemis/agentic/`

| File | Owner spec | Purpose |
|---|---|---|
| `__init__.py`, `types.py` | **AGENT-types** (Wave 0) | shared dataclasses/enums/Protocols; the one barrel — others import, declare it a Prerequisite |
| `checkpoint.py` | **AGENT-checkpoint** (Wave 1) | thread-keyed SQLite checkpoint/resume |
| `inbox.py` | **AGENT-inbox** (Wave 1) | `AgentInbox` + `AskOwnerTool` (headless pause-to-ask) |
| `authority.py` | **AGENT-authority** (Wave 1) | blast-radius classify + graduated allowlist (wraps GATE) |
| `executor.py`, `reliability.py` | **AGENT-spine** (Wave 2) | `plan→act→verify` loop + reliability spine; composes Wave-1 seams |
| `rungs/__init__.py`, `rungs/introspect.py`, `rungs/fileops.py` | **AGENT-rung01** (Wave 3) | Rung 0 read-only introspection + Rung 1 reversible file ops |
| `coder/__init__.py`, `coder/workspace.py`, `coder/router.py`, `coder/subsystem.py` | **AGENT-coder** (Wave 4) | OpenHands embed + LiteLLM router + planner/plan-code split |
| `rungs/command.py`, `sandbox.py` | **AGENT-rung2** (Wave 5) | sandboxed command exec + Windows restricted-token/Job-Object sandbox seam |

Waves = dependency order. Wave 1 (checkpoint/inbox/authority) are mutually file-disjoint → parallel.
Spine (Wave 2) composes them. Rung01 (3), coder (4), rung2 (5) each depend on the spine.

## Shared types — `agentic/types.py` (AGENT-types owns)

```python
class ExecutorState(StrEnum):          # phase tracking + resume
    PLANNING = "planning"; ACTING = "acting"; VERIFYING = "verifying"
    WAITING_OWNER = "waiting_owner"; DONE = "done"; FAILED = "failed"

class PlanStep(BaseModel):             # one atomic act+verify unit
    id: str; description: str
    tool_ref: str                      # fq tool id in the ToolRegistry
    args: dict[str, str | int | float | bool]
    verify: str                        # deterministic read-back check id (NOT model self-judgement)

class Plan(BaseModel): task_id: str; steps: tuple[PlanStep, ...]

class StepResult(BaseModel): step_id: str; ok: bool; output: str; verified: bool

class Task(BaseModel):                 # the unit the executor runs
    id: str; goal: str
    unattended: bool = False           # ADR-024 supervised/unattended flag
    token_budget: int; step_budget: int

class Crossing(StrEnum): IN_SANDBOX = "in_sandbox"; BOUNDARY = "boundary"   # ADR-031 C

# Protocols (structural seams — concrete impls in their owner specs)
class CheckpointStore(Protocol):
    def save(self, task_id: str, state: ExecutorState, plan: Plan, step_index: int,
             last_verified_output: str | None) -> None: ...
    def load(self, task_id: str) -> CheckpointRow | None: ...   # CheckpointRow: a small frozen row

class OwnerInbox(Protocol):            # AskOwnerTool is the executor-facing wrapper over this
    async def ask(self, question: str, *, options: tuple[str, ...] = (),
                  timeout_s: int = 0) -> str | None: ...        # None = timed out (partial-result path)
```

## Key seams (the load-bearing interlocks)

1. **Executor loop (`executor.py`)** — `async def run(task: Task) -> TaskResult`:
   `plan(task)` via the planner LLM → for each `PlanStep`: `authority.authorize(step)` → act
   (dispatch `step.tool_ref` through the existing **ToolRegistry**, same as reactions/modules) →
   `verify` (deterministic read-back by `step.verify` id — file exists / exit 0 / expected output;
   **never** "model says it worked") → `checkpoint.save(...)`. **Phase-boundary context reset:**
   failed-attempt context is dropped across plan/act/verify boundaries (ADR-031 F, highest-leverage).
   **Pre-call budgets + circuit-breaker** (`reliability.py`): token/step ceilings checked pre-call; a
   no-progress detector trips → escalate to inbox, never silent abort. On ambiguity/blocked →
   `AskOwnerTool` (state→`WAITING_OWNER`, checkpointed, resumable).

2. **CheckpointStore (`checkpoint.py`)** — owner-private SQLite (mirror `ReactionLedger`
   construction: `Settings` + `KeyProvider`, `sqlcipher_open`, `OWNER_PRIVATE` scope). One row per
   `task_id`: state + plan JSON + step_index + last_verified_output. `load` returns it for resume.

3. **AgentInbox / AskOwnerTool (`inbox.py`)** — headless (refinement a): a pending question persists
   (owner-private), delivers via **`NtfyDelivery`** (M6-c) — "Artemis needs a decision: …"; the owner
   answers via the dev CLI / API; `ask` resolves or times out (`None` → executor takes the
   partial-result/park path). The `AskOwnerTool` is the executor-facing tool wrapper; `AgentInbox` is
   the persistence+delivery+resolve store. **Shared primitive** — the coding subsystem reuses it.

4. **AuthorityGate (`authority.py`)** — ADR-031 C blast-radius rule. `classify(tool_ref, args) ->
   Crossing` (in-sandbox = no network, workspace-confined, disposable; boundary = network / writes
   outside workspace / real-world effect). `authorize(step) -> auto | needs_approval`: `IN_SANDBOX` →
   auto; `BOUNDARY` → graduated allowlist (owner-private store keyed by a command/script signature):
   novel crossing → stage via **`ActionStagingService.stage`** + notify via inbox; once approved, that
   *specific* signature graduates to auto; a new crossing by an approved script re-asks. Specific, not
   a blank cheque.

5. **Coder subsystem (`coder/`)** — binds OpenHands **V1 `openhands-sdk`** behind Artemis layers
   (ADR-031 Refinement 2026-06-26): `workspace.py` = the workspace-abstraction seam (`LocalWorkspace`
   on Windows-dev wrapped by `sandbox.py`; `DockerWorkspace`/remote on Mac — config-only swap);
   `router.py` = LiteLLM per-task backend (Codex/DeepSeek/GLM/Ollama); `subsystem.py` = the
   planner(Claude/Opus)/coder split + a custom OpenHands `ConfirmationPolicy` that defers
   `WAITING_FOR_CONFIRMATION` to the Artemis `AuthorityGate`/inbox (no executor-layer changes).

6. **Sandbox (`sandbox.py`, AGENT-rung2)** — Artemis Windows **restricted-token + Job Object** wrap
   (reuse the `apex-coder`/Codex isolation pattern) around the local runtime / Rung-2 command exec;
   built swap-able (the workspace seam) → Docker/remote on Mac. macOS `sandbox-exec` interim stays the
   Mac analogue (ADR-031 C).

## New dependencies (per spec, typosquat-checked at gate)
- AGENT-spine: `pydantic-ai` (the executor primitive — ADR-022/031 D engine).
- AGENT-coder: `openhands-sdk` (+ `openhands-tools`/`-agent-server`/`-workspace`), `litellm`.
  (Heavy; an optional `[agentic]` dep group — keep the dev base lean, mirror the docling-extra precedent.)

## What this series does NOT cover (out of pass)
Rung 3 (app-control + Anthropic Computer Use vision loop), Rung 4 (host-watch), GEPA self-improvement —
all Mac-gated/end-state (ADR-031 G Phases 5–7). The 4 agentic UI panels — deferred to BACKLOG (headless
channels suffice for the dev build).
