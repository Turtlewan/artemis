# Spec: v2-00 — Scaffold + Ports

status: ready
slice: 0
coder_effort: medium

## Identity
Scaffold the v2 Artemis Python project and define the five typed harness ports (the swappable seams). See [`docs/v2/architecture.md`](../v2/architecture.md) §2–9. v1 is archived behind the `archive/v1` tag and is OUT OF SCOPE for this spec.

> PREREQUISITE (manual, before this spec): `git tag archive/v1` at the v1 HEAD, then remove the v1 `src/artemis/` tree. `client/` is untouched. This spec assumes a clean (or absent) `src/artemis/`.

## Files to change
- `pyproject.toml` — create (uv project, deps, ruff/mypy/pytest config)
- `src/artemis/__init__.py` — create (package marker + version)
- `src/artemis/types.py` — create (shared dataclasses/Pydantic models used by ports)
- `src/artemis/ports/__init__.py` — create (re-export the five ports)
- `src/artemis/ports/model.py` — create (`ModelPort`)
- `src/artemis/ports/memory.py` — create (`MemoryPort`)
- `src/artemis/ports/transport.py` — create (`TransportPort`)
- `src/artemis/ports/capabilities.py` — create (`CapabilityStore`)
- `src/artemis/ports/scheduler.py` — create (`Scheduler`)
- `tests/test_ports_smoke.py` — create (import + protocol-existence smoke test)

## Exact changes

### Task 1 — project scaffold (`pyproject.toml`)
- `[project]` name `artemis`, `requires-python = ">=3.12"`, deps: `pydantic>=2`.
- `[dependency-groups]` `dev = ["mypy", "ruff", "pytest", "pytest-asyncio"]`.
- `[tool.mypy]` `strict = true`, `files = ["src", "tests"]`.
- `[tool.ruff]` line-length 100; `[tool.pytest.ini_options]` `asyncio_mode = "auto"`, `testpaths = ["tests"]`.
- `[tool.setuptools.packages.find]` (or hatchling) targeting `src/`.

### Task 2 — shared types (`src/artemis/types.py`)
Pydantic models / dataclasses (frozen where natural):
- `Message(role: Literal["system","user","assistant"], content: str)`
- `ModelResponse(text: str, model_id: str, structured: dict | None, finish_reason: str, usage: Usage)`; `Usage(prompt_tokens, completion_tokens, total_tokens)`
- `MemoryItem(content: str, layer: "MemoryLayer", tags: list[str] = [], metadata: dict = {})`
- `MemoryLayer = Literal["constitution","rules","semantic","episodic","corpus","capability","working"]`
- `RetrievedContext(items: list[MemoryItem], token_cost: int, truncated: bool)`
- `InboundMessage(transport: str, identity: str, text: str, attachments: list = [])`
- `OutboundMessage(transport: str, identity: str, text: str, proactive: bool = False)`
- `SkillDraft(name: str, description: str, body: str, tool_script: str | None, uses: list[str] = [], secrets: list[str] = [], tests: str | None)`
- `Skill(name, description, version: int, path: str, tags: list[str], uses: list[str], secrets: list[str])`; `StagedSkill(id: str, draft: SkillDraft)`
- `ScheduledJob(id: str, cron: str | None, run_at: str | None, payload: dict)`; `EventTrigger(kind: str, match: dict)`

### Task 3 — the five ports (typed `Protocol`, `@runtime_checkable`)
`src/artemis/ports/model.py`:
```python
@runtime_checkable
class ModelPort(Protocol):
    async def complete(self, *, messages: Sequence[Message], model: str | None = None,
                       response_schema: dict | None = None, temperature: float = 0.7,
                       max_tokens: int | None = None) -> ModelResponse:
        """One completion across any provider. When response_schema is given, the impl
        down-converts it per backend (strict OpenAI/Codex vs lenient Ollama vs Anthropic
        tool input_schema), validates the result client-side, and re-asks on failure."""
        ...
```
`src/artemis/ports/memory.py`:
```python
@runtime_checkable
class MemoryPort(Protocol):
    async def write(self, item: MemoryItem) -> None:
        """Consolidating write (ADD/UPDATE/DELETE/NOOP) — never blind-append."""
        ...
    async def retrieve(self, query: str, *, token_budget: int,
                       layers: Sequence[str] | None = None) -> RetrievedContext:
        """Retrieve wide, rerank + MMR-dedup, cap to token_budget, summarize overflow."""
        ...
    async def consolidate(self) -> None:
        """Background: episodic to semantic, build/refresh summaries, merge near-dupes."""
        ...
    async def forget(self, *, max_age_days: int | None = None,
                     min_salience: float | None = None) -> None:
        """Demote/decay/archive — never hard-delete."""
        ...
```
`src/artemis/ports/transport.py`:
```python
@runtime_checkable
class TransportPort(Protocol):
    name: str
    def receive(self) -> AsyncIterator[InboundMessage]:
        """Ingress stream; identity resolved per transport (allowlist/session)."""
        ...
    async def send(self, msg: OutboundMessage) -> None:
        """Egress, including proactive push."""
        ...
```
`src/artemis/ports/capabilities.py`:
```python
@runtime_checkable
class CapabilityStore(Protocol):
    async def stage(self, draft: SkillDraft) -> StagedSkill:
        """Write an authored capability to the quarantine staging area."""
        ...
    async def promote(self, staged_id: str) -> Skill:
        """Promote a staged skill that passed the test-before-trust gate into the library."""
        ...
    async def retrieve(self, query: str, *, k: int = 5,
                       tags: Sequence[str] | None = None) -> list[Skill]:
        """Semantic retrieval by description embedding + optional tag filter."""
        ...
    def get(self, name: str) -> Skill | None: ...
```
`src/artemis/ports/scheduler.py`:
```python
@runtime_checkable
class Scheduler(Protocol):
    async def schedule(self, job: ScheduledJob) -> str:
        """Register a durable time-based job (survives restart)."""
        ...
    async def on_event(self, trigger: EventTrigger,
                       handler: Callable[[dict], Awaitable[None]]) -> str:
        """Register an event-based trigger."""
        ...
    async def run(self) -> None:
        """The always-on heartbeat: drain the event queue + fire due jobs."""
        ...
    def cancel(self, job_id: str) -> None: ...
```
`src/artemis/ports/__init__.py` re-exports all five.

### Task 4 — smoke test (`tests/test_ports_smoke.py`)
- `import artemis` succeeds; `artemis.__version__` is a str.
- Import all five ports from `artemis.ports`; assert each is a `typing.Protocol` and `@runtime_checkable` (e.g. `isinstance(object(), ModelPort)` is callable without error / a trivial stub class structurally satisfies it).
- A minimal in-test stub implementing `ModelPort` passes `isinstance(stub, ModelPort)`.

## Acceptance criteria
1. Task 1: `uv sync` resolves; `uv run python -c "import artemis"` exits 0.
2. Task 2–3: `uv run mypy` → no errors (strict).
3. Task 3: all five ports importable from `artemis.ports`.
4. Task 4: `uv run pytest -q tests/test_ports_smoke.py` → passes.

## Commands to run
```
uv sync
uv run ruff check src tests
uv run mypy
uv run pytest -q
```
