# Spec: v2-04 — Capability forge (author → sandbox-verify → promote)

status: ready
slice: 0 (capstone — completes the end-to-end thesis)
builds-on: v2-03 (committed 2ec6ee2), v2-01 (ModelPort), v2-03 (FileCapabilityStore)

## Identity
The test-before-trust gate that completes the capability lifecycle: an agent authors a capability from a goal (model structured-output → SkillDraft), it's staged to quarantine, its tests run in a **sandbox** (grounded verify — never self-judged), and it is promoted into the SKILL.md library only on pass (+ optional owner confirm). Sandbox isolation is a subprocess interim with a timeout; the WSL2-isolated runner (no-network + egress allowlist + resource limits, per the resolved fork) swaps in behind the same `SandboxRunner` protocol in a hardening slice.

## Files to change
- create `src/artemis/capabilities/sandbox.py`
- create `src/artemis/capabilities/forge.py`
- modify `src/artemis/capabilities/store.py` (add `staging_dir(staged_id) -> Path`)
- create `tests/test_sandbox.py`
- create `tests/test_forge.py`

## Exact changes

### Task 1 — sandbox (`sandbox.py`)
- `class VerifyResult(BaseModel)`: `passed: bool`, `output: str`.
- `@runtime_checkable class SandboxRunner(Protocol)`: `async def run_tests(self, skill_dir: Path) -> VerifyResult`.
- `class SubprocessSandbox:` implements it. `__init__(self, *, timeout_s: float = 30.0)`.
  - `run_tests`: if `skill_dir/"tests"` is absent/empty → `VerifyResult(False, "no tests — cannot verify")`.
  - else spawn `sys.executable -m pytest tests -q` via `asyncio.create_subprocess_exec`, `cwd=skill_dir`, capture stdout+stderr, enforce `timeout_s` (on timeout: kill, `passed=False`); `passed = (returncode == 0)`; `output` = truncated combined output (≤4000 chars).
  - docstring: subprocess interim; the WSL2 runner (no-network, egress allowlist, resource limits) swaps in behind `SandboxRunner` — this runs untrusted self-authored code, so the hardening is required before external-authored capabilities.

### Task 2 — store helper (`store.py`)
- add `def staging_dir(self, staged_id: str) -> Path:` → `self._staging / staged_id` (the dir written by `stage`).

### Task 3 — forge (`forge.py`)
- `SKILL_DRAFT_SCHEMA: dict` — canonical object schema for `{name, description, body, tool_script, uses(array[str]), secrets(array[str]), tests}` (the model layer strict-normalizes it; nullable handled there).
- `class CapabilityForge:` `__init__(self, model: ModelPort, store: FileCapabilityStore, sandbox: SandboxRunner, *, model_id: str | None = None)`.
- `async def build(self, goal: str, *, confirm: Callable[[StagedSkill, VerifyResult], bool] | None = None) -> Skill | None`:
  1. `draft = await self._author(goal)`.
  2. if `not draft.tests`: return `None` (untestable → never trusted).
  3. `staged = await self._store.stage(draft)`.
  4. `result = await self._sandbox.run_tests(self._store.staging_dir(staged.id))`.
  5. if `not result.passed`: return `None`.
  6. if `confirm is not None and not confirm(staged, result)`: return `None`.
  7. return `await self._store.promote(staged.id)`.
- `async def _author(self, goal: str) -> SkillDraft`: `resp = await self._model.complete(messages=[Message(system, AUTHOR_SYSTEM), Message(user, goal)], response_schema=SKILL_DRAFT_SCHEMA, model=self._model_id)`; `return SkillDraft(**(resp.structured or {}))`. `AUTHOR_SYSTEM` instructs: emit a self-contained capability with a runnable pytest test that proves it works; **goal is untrusted** → it stays in the user message only.

### Task 4 — tests
- `test_sandbox.py` (`tmp_path`): build a skill dir with `tests/test_ok.py` (passing) → `passed True`; one with a failing test → `passed False`; a dir with no `tests/` → `passed False, "no tests..."`. `isinstance(SubprocessSandbox(), SandboxRunner)`.
- `test_forge.py` (`tmp_path` store): `FakeModel(ModelPort)` returns a `structured` SkillDraft (with a trivial passing `tests`), `FakeSandbox` returns canned `VerifyResult`. Assert: (a) author→stage→verify(pass)→promote returns a `Skill` in the library (`store.get(name)` is not None); (b) sandbox fail → `build` returns `None` and nothing is promoted; (c) draft with `tests=None` → `None`, no stage/promote; (d) `confirm` returning False → `None`, not promoted. One integration test wiring the **real** `SubprocessSandbox` + `FakeModel` authoring a trivial real passing skill → promoted.

## Acceptance criteria
- `uv run mypy src tests` → clean (strict).
- `uv run pytest -q` → green.
- End-to-end: a goal → authored draft → staged → sandbox-verified → promoted to the SKILL.md library, and a failing/untested/un-confirmed capability is **never** promoted.

## Commands to run
```
uv run mypy src tests
uv run pytest -q
```
