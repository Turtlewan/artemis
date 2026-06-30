# Spec: v2-02 — Minimal plan→act→verify spine

status: ready
slice: 0
builds-on: v2-01 (ModelPort + ModelClient, committed cb9755e)

## Identity
The thin orchestration spine: given a task, plan → act → **grounded-verify** → done, with checkpointed state for observability/resume. Verification is execution-grounded (a caller-supplied acceptance check), never model-self-judged. Delegation of a whole task to a subscription sub-agent is a documented seam, deferred. This spine is what v2-03 drives to author+verify a capability.

## Files to change
- create `src/artemis/spine/__init__.py`
- create `src/artemis/spine/types.py`
- create `src/artemis/spine/checkpoint.py`
- create `src/artemis/spine/spine.py`
- create `tests/test_checkpoint.py`
- create `tests/test_spine.py`

## Exact changes

### Task 1 — spine types (`types.py`)
- `RunState = Literal["planning","acting","verifying","done","failed"]`.
- `class Task(BaseModel)`: `id: str`, `goal: str`, `context: str = ""`, `max_retries: int = 1`.
- `class Plan(BaseModel)`: `steps: list[str]`.
- `class RunResult(BaseModel)`: `task_id: str`, `state: RunState`, `output: str`, `plan: Plan | None`, `attempts: int`.
- `Acceptance = Callable[[str], bool]` (type alias; takes the act output, returns pass/fail) — the grounded check.
- `PLAN_SCHEMA: dict` — JSON schema `{"type":"object","properties":{"steps":{"type":"array","items":{"type":"string"}}}}` (canonical; the model layer strict-normalizes it).

### Task 2 — checkpoint (`checkpoint.py`)
- `@runtime_checkable class Checkpoint(Protocol)`: `def save(self, task_id: str, state: RunState, data: dict) -> None` and `def load(self, task_id: str) -> dict | None` (returns the latest saved `{state, data}` or None).
- `class InMemoryCheckpoint:` dict-backed; implements `Checkpoint`.
- `class JsonFileCheckpoint:` `__init__(self, dir: Path)`; writes `<dir>/<task_id>.json` (latest snapshot, overwrite); durable across process restarts; implements `Checkpoint`.

### Task 3 — the spine (`spine.py`)
- `class Spine:` `__init__(self, model: ModelPort, *, checkpoint: Checkpoint | None = None, model_id: str | None = None)` (default `checkpoint = InMemoryCheckpoint()`).
- `async def run(self, task: Task, *, acceptance: Acceptance | None = None) -> RunResult`:
  1. **PLAN** — `checkpoint.save(task.id, "planning", {...})`; `resp = await model.complete(messages=[system+goal], response_schema=PLAN_SCHEMA, model=self._model_id)`; parse `Plan` from `resp.structured`.
  2. **ACT** — `checkpoint.save(task.id, "acting", {...})`; build a prompt from `task.goal + task.context + plan.steps`; `out = (await model.complete(messages=[...], model=self._model_id)).text`.
  3. **VERIFY** — if `acceptance is None`: state = `"done"`. Else `checkpoint.save(task.id,"verifying",...)`; if `acceptance(out)` → `"done"`; else if attempts remain (`< task.max_retries+1`): re-ACT with the failure noted in the prompt, then re-verify; on final failure → `"failed"`.
  4. `checkpoint.save(task.id, final_state, {...})`; return `RunResult(task_id, state, output=out, plan=plan, attempts=n)`.
- `goal`/`context` are **untrusted input** (may come from email/web later): place Artemis instructions in the `system` message, the goal/context only in `user` messages — never concatenate goal into the system prompt. (State this in a docstring; classifier pre-filter deferred.)
- delegation seam: a `# TODO(slice-1): delegate-whole-task to a subscription sub-agent` comment at the ACT step.

### Task 4 — tests
- `test_checkpoint.py`: `InMemoryCheckpoint` and `JsonFileCheckpoint` (tmp_path) round-trip save/load; both satisfy `isinstance(..., Checkpoint)`; load of unknown id → None; JsonFile persists across a fresh instance.
- `test_spine.py`: a `FakeModel(ModelPort)` returning a canned plan (as `structured`) then canned act text. Assert: (a) no-acceptance run → `state == "done"`, output set, checkpoint saw `planning`→`acting`→`done`; (b) acceptance pass → `done` in 1 attempt; (c) acceptance fails once then passes on retry → `done`, `attempts == 2`; (d) acceptance always fails → `state == "failed"`, `attempts == max_retries+1`.

## Acceptance criteria
- `uv run mypy src tests` → clean (strict).
- `uv run pytest -q` → green.
- Spine drives plan→act→verify with a grounded acceptance check and records checkpoint transitions; untrusted goal stays out of the system prompt.

## Commands to run
```
uv run mypy src tests
uv run pytest -q
```
