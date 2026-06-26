---
spec: AGENT-types
status: draft
cross_model_review: false
token_profile: lean
autonomy_level: L2
---

# Spec: AGENT-types — shared agentic types + Protocols (Wave 0 foundation barrel)

**Identity:** Creates the `src/artemis/agentic/` package and `types.py` — the shared dataclasses,
enums, and structural Protocols every AGENT-* spec imports (ADR-031 dev-buildable engine). The one
barrel; all later specs declare it a Prerequisite (ADR-029 single-owner).
<!-- → why: docs/technical/adr/ADR-031-agentic-runtime-host-computer-use.md + docs/drafts/AGENT-engine-design.md (§ Shared types). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- `src/artemis/agentic/` does NOT yet exist (greenfield) — this spec creates the package `__init__.py`. → impact: Stop (if it exists, another spec already created it and file ownership conflicts).
- The project targets Python ≥3.12 (`pyproject.toml requires-python = ">=3.12"`, runtime 3.12.10), so `enum.StrEnum` is available and is the idiom for string enums. → impact: Caution (on <3.12 fall back to `(str, Enum)`; not applicable here).
- Pydantic v2 is the model lib; the frozen/extra-forbid idiom is `model_config = ConfigDict(frozen=True, extra="forbid")` (as in `src/artemis/staging/model.py` and `src/artemis/runtime_config.py` `ReactionConfig`). Match it. → impact: Caution.
- `typing.Protocol` is the structural-seam idiom; concrete implementations live in their owner specs (AGENT-checkpoint, AGENT-inbox). This spec defines ONLY the Protocols + data types, no behaviour, no I/O. → impact: Stop (adding behaviour here couples the barrel to concrete deps).
- No new third-party dependency is introduced (stdlib + pydantic only). → impact: Stop.

Simplicity check: considered defining each type in its consumer spec instead of a shared barrel — rejected: the executor, checkpoint, inbox, and authority specs all reference `Plan`/`ExecutorState`/`Crossing` and the `CheckpointStore`/`OwnerInbox` Protocols, so a single owned barrel (ADR-029) is the minimal coherent home. This is the smallest possible foundation spec.

## Prerequisites
- Specs that must be complete first: none (Wave 0 foundation).
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/agentic/__init__.py` | create | Package marker; lazy re-export of the public types (mirror the `reactions/__init__.py` `__getattr__` pattern if re-exporting, else a simple explicit import block). |
| `src/artemis/agentic/types.py` | create | Shared enums, models, and Protocols per the backbone § Shared types. |
| `tests/test_agent_types.py` | create | Model validate/reject + Protocol-importability tests. |

## Exact changes (`types.py`)
```python
from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ExecutorState(StrEnum):
    PLANNING = "planning"
    ACTING = "acting"
    VERIFYING = "verifying"
    WAITING_OWNER = "waiting_owner"
    DONE = "done"
    FAILED = "failed"


class Crossing(StrEnum):
    IN_SANDBOX = "in_sandbox"
    BOUNDARY = "boundary"


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    description: str
    tool_ref: str
    args: dict[str, str | int | float | bool] = {}
    verify: str  # deterministic read-back check id (never model self-judgement)


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    task_id: str
    steps: tuple[PlanStep, ...]


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    step_id: str
    ok: bool
    output: str
    verified: bool


class Task(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    goal: str
    unattended: bool = False
    token_budget: int
    step_budget: int


class CheckpointRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    task_id: str
    state: ExecutorState
    plan: Plan
    step_index: int
    last_verified_output: str | None = None


class CheckpointStore(Protocol):
    def save(
        self,
        task_id: str,
        state: ExecutorState,
        plan: Plan,
        step_index: int,
        last_verified_output: str | None,
    ) -> None: ...
    def load(self, task_id: str) -> CheckpointRow | None: ...


class OwnerInbox(Protocol):
    async def ask(
        self, question: str, *, options: tuple[str, ...] = (), timeout_s: int = 0
    ) -> str | None: ...
```
(`__init__.py` re-exports the public names so consumers `from artemis.agentic import Plan, ExecutorState, ...`. Use the lazy `__getattr__` pattern if matching `reactions/__init__.py`; a plain import block is acceptable since `types.py` has no heavy deps.)

## Tasks
- [ ] Task 1: Create `src/artemis/agentic/__init__.py` + `src/artemis/agentic/types.py` with the enums, frozen models, and Protocols per Exact changes. — files: `src/artemis/agentic/__init__.py`, `src/artemis/agentic/types.py` — done when: `from artemis.agentic import ExecutorState, Crossing, PlanStep, Plan, StepResult, Task, CheckpointRow, CheckpointStore, OwnerInbox` succeeds; `uv run mypy` clean.
- [ ] Task 2: Tests. — files: `tests/test_agent_types.py` — done when: a valid `Plan(task_id=..., steps=(PlanStep(...),))` constructs; `PlanStep(extra=1)` raises (extra forbid); `Task` requires `token_budget`/`step_budget`; a trivial class implementing `CheckpointStore`/`OwnerInbox` type-checks (Protocol structural conformance); `uv run pytest -q tests/test_agent_types.py` passes.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/__init__.py`, `src/artemis/agentic/types.py`, `tests/test_agent_types.py` |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The three files above, by name. |
| `git commit` | "feat: AGENT-types shared agentic types + Protocols (ADR-031 engine foundation)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installs. |

## Specialist Context
### Security
(none — pure type/Protocol definitions; no I/O, no data at rest, no external surface.)

### Performance
(none.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/types.py` | Module + type docstrings (one line each; cite the backbone seam). |
| ADR | (none) | ADR-031 already records the design. |

## Acceptance Criteria
- [ ] Package + types importable → verify: `from artemis.agentic import Plan, ExecutorState, Crossing, PlanStep, StepResult, Task, CheckpointRow, CheckpointStore, OwnerInbox` succeeds.
- [ ] Frozen/extra-forbid enforced → verify: `PlanStep(id="a", description="d", tool_ref="t", verify="v", bogus=1)` raises; models are immutable.
- [ ] Protocol conformance → verify: a minimal stub implementing `CheckpointStore` / `OwnerInbox` type-checks under `uv run mypy`.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
