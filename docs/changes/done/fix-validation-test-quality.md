---
spec: fix-validation-test-quality
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: flash
---

# Spec: fix-validation-test-quality — close the mypy-scope gap, de-flake the embedder fake, tighten hollow conformance asserts

**Identity:** Mechanical test-quality cleanup of the validation suite: make `mypy` cover `tests/` (the root cause that hid 14 errors), make the manifest `FakeEmbedder` deterministic across processes (kills the one flaky test), tighten two hollow conformance assertions so they actually type-check, and remove three cosmetic residues. No production behaviour changes; no Mac/MLX/Mini dependency — buildable on WSL2 now.
→ why: docs/findings/prebuild-test-review-findings.md § Bucket 1 (pre-build test-review synthesis).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->
<!-- Split rule: exceeds the 3-file guide (7 files) but is ONE logical phase — independent, trivial, mechanical test-quality fixes with zero cross-file logic. Kept as one spec deliberately (a 15-min cleanup; splitting adds overhead, no value). Each task is self-contained and individually verifiable. -->

## Assumptions
- The validation suite is at commit `5975b30`: 121 tests pass · ruff clean · `uv run mypy src` clean (43 files) but `uv run mypy src tests` reports **14 errors** — 10 in `tests/test_vector_store.py` (`no-untyped-def` on `tmp_path`), 4 in `tests/test_offline_compose.py` (list-invariance on fake embed returns). → impact: Stop (these counts are the acceptance target; re-confirm with `uv run mypy src tests` before editing).
- `src/artemis/ports/types.py` defines `Vector = Sequence[float]` (line 15). `artemis.ports` exports the `VectorStore` Protocol (importable as `from artemis.ports import VectorStore`, per `tests/test_ports.py`). → impact: Stop.
- `[tool.mypy]` in `pyproject.toml` sets `strict = true` + `plugins` + `exclude = [".venv/", "scripts/"]` but has **no `files`/`packages` key**, so a bare `mypy` does not pin its targets — build sessions ran `mypy src` only. → impact: Stop (the fix adds `files = ["src", "tests"]` so any `mypy` invocation covers both; `scripts/` stays excluded).
- `tests/test_ports.py::test_static_conformance` already uses typed assignments (`vs: VectorStore = _MinimalVectorStore()`, `r: Router = _MinimalRouter()`); it was simply never type-checked. → impact: Low (no code change; resolved by the `files` change — verified in acceptance).
- `pytest` config has `asyncio_mode = "auto"`, so unmarked `async def test_*` already run; adding `@pytest.mark.asyncio` is consistency-only. → impact: Low.

## Files to change
1. **modify** `pyproject.toml` — add `files = ["src", "tests"]` to `[tool.mypy]`.
2. **modify** `tests/test_manifest_registry.py` — F6-a (deterministic `hashlib` hash) + F6-b (`vs: VectorStore`).
3. **modify** `tests/test_offline_compose.py` — F11-a (widen fake embed return annotations to `Vector`).
4. **modify** `tests/test_vector_store.py` — F12-a (`tmp_path: Path` annotations).
5. **modify** `src/artemis/ports/types.py` — F5-a (remove stray duplicate docstring).
6. **modify** `tests/test_router_brain.py` — F7-a (correct a stale comment).
7. **modify** `tests/test_model_auth.py` — F10-b (add `@pytest.mark.asyncio` to the 2 async tests).

## Exact changes

### 1. `pyproject.toml` — make mypy cover tests by default
In the `[tool.mypy]` table, add a `files` key (leave `strict`, `plugins`, `exclude` untouched):
```toml
[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
files = ["src", "tests"]
exclude = [
    ".venv/",
    "scripts/",
]
```

### 2. `tests/test_manifest_registry.py`
**F6-a — deterministic embedder.** `math` is already imported; add `import hashlib` to the stdlib import block (alphabetical, before `import json`). Replace the `_hash_vec` body's per-word loop so it uses a process-stable digest instead of builtin `hash()`:
```python
    def _hash_vec(self, text: str) -> Vector:
        """Build a fixed-dim vector from word-level hashes (process-stable)."""
        vec = [0.0] * self.DIMENSION
        words = text.lower().split()
        for word in words:
            bucket = hashlib.sha256(word.encode()).digest()[0] % self.DIMENSION
            vec[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec
```
**F6-b — real conformance assertion.** Add `VectorStore` to the ports import (`from artemis.ports import InMemoryToolIndex, ToolRegistry` is actually `from artemis.registry import ...`; add a new line `from artemis.ports import VectorStore`). Change the hollow assignment at `test_port_conformance`:
```python
        index = InMemoryToolIndex()
        # This line type-checks under mypy --strict: InMemoryToolIndex must
        # structurally satisfy the VectorStore protocol.
        vs: VectorStore = index
        assert vs is not None
```
Then remove the now-unused `from typing import Any` import (line 13) — it has no other use in the file.

### 3. `tests/test_offline_compose.py` — F11-a
Add `Vector` to the imports: `from artemis.ports.types import Usage, Vector`. Widen the three fake embed return annotations from concrete `list[list[float]]`/`list[float]` to the port types (the return literals stay unchanged — contextual typing makes them conform):
```python
    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[0.1] * self._dim for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        return [0.1] * self._dim
```
and on `_FakeModel`:
```python
    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[0.1] * 8 for _ in texts]
```

### 4. `tests/test_vector_store.py` — F12-a
Add `from pathlib import Path` to the imports (after `import math`). Annotate the `tmp_path` parameter as `Path` on the helper and all 9 test functions:
```python
def _store(tmp_path: Path, dim: int = _DIM) -> LanceDBVectorStore:
```
and for each test:
```python
def test_dense_round_trip(tmp_path: Path) -> None:
def test_cosine_metric_contract(tmp_path: Path) -> None:
def test_fts_round_trip(tmp_path: Path) -> None:
def test_fts_incremental_add_is_searchable(tmp_path: Path) -> None:
def test_scope_isolation_dense_and_fts(tmp_path: Path) -> None:
def test_dimension_lock_on_write(tmp_path: Path) -> None:
def test_dimension_lock_on_reopen(tmp_path: Path) -> None:
def test_invalid_scope_rejected(tmp_path: Path) -> None:
def test_empty_store_returns_nothing(tmp_path: Path) -> None:
```

### 5. `src/artemis/ports/types.py` — F5-a
Delete the stray duplicate docstring line 20 (the second `"""Engine-agnostic embedding vector."""` that follows the `Mode` docstring). Result:
```python
Mode = str
"""Retrieval mode: ``hybrid``, ``agentic``, or ``graph``."""
```

### 6. `tests/test_router_brain.py` — F7-a
At the comment in `test_brain_degrade_on_tool_error` (lines ~234-236), replace the inaccurate "bag-of-words hash" wording with the truth for this file's fake (a constant unit vector matches every tool):
```python
    # This file's FakeEmbedder returns a constant unit vector, so every query
    # matches every registered tool (cosine = 1.0); the fail tool therefore
    # dispatches and raises, exercising the degrade path.
    response = await brain.respond("fail on purpose", "owner-private")
```

### 7. `tests/test_model_auth.py` — F10-b
Add `import pytest` and decorate the two `async def` tests for consistency with the rest of the suite:
```python
@pytest.mark.asyncio
async def test_complete_sends_bearer_on_wire() -> None:
```
(Apply the same decorator to any other `async def test_*` in the file.)

## Tasks
- [ ] Task 1: Add `files = ["src", "tests"]` to `[tool.mypy]` in `pyproject.toml` — files: `pyproject.toml` — done when: `uv run --frozen mypy` (no args) type-checks both `src` and `tests`.
- [ ] Task 2: F6-a deterministic `_hash_vec` + F6-b `vs: VectorStore` (+ drop unused `Any`) — files: `tests/test_manifest_registry.py` — done when: the file imports `hashlib` + `VectorStore`, `_hash_vec` uses `hashlib.sha256`, `test_port_conformance` annotates `vs: VectorStore`, no `from typing import Any`.
- [ ] Task 3: F11-a widen fake embed return annotations — files: `tests/test_offline_compose.py` — done when: `_FakeEmbedder.embed_documents`/`embed_query` and `_FakeModel.embed` are annotated with `Vector`/`list[Vector]`.
- [ ] Task 4: F12-a annotate `tmp_path: Path` — files: `tests/test_vector_store.py` — done when: `Path` is imported and all 10 functions annotate `tmp_path: Path`.
- [ ] Task 5: F5-a remove stray docstring — files: `src/artemis/ports/types.py` — done when: only one `"""Engine-agnostic embedding vector."""` remains in the file (on `Vector`).
- [ ] Task 6: F7-a correct stale comment — files: `tests/test_router_brain.py` — done when: the comment no longer says "bag-of-words hash" and describes the constant-unit-vector behaviour.
- [ ] Task 7: F10-b add `@pytest.mark.asyncio` — files: `tests/test_model_auth.py` — done when: every `async def test_*` carries the marker and `pytest` import is present.

## Acceptance criteria
1. **mypy clean over src + tests** → `uv run --frozen mypy src tests` exits 0 (was 14 errors). Also `uv run --frozen mypy` (no args) exits 0.
2. **No flaky test under hash randomisation** → the previously-flaky test is stable across seeds:
   `for s in 0 1 2 3 4; do PYTHONHASHSEED=$s uv run --frozen pytest -q tests/test_manifest_registry.py::TestToolRegistry::test_retrieve_tools_returns_fq_ids || exit 1; done` → all pass.
3. **Full suite still green** → `uv run --frozen pytest -q` → 121 passed (0 failed, no new skips beyond the existing host-conditional FTS skips).
4. **Lint clean** → `uv run --frozen ruff check .` → all checks passed.
5. **No production behaviour change** → `git diff --stat` shows only the 7 files above; `src/` changes limited to the one-line docstring deletion in `types.py`.

## Commands to run
```bash
uv run --frozen mypy src tests
uv run --frozen mypy
for s in 0 1 2 3 4; do PYTHONHASHSEED=$s uv run --frozen pytest -q tests/test_manifest_registry.py::TestToolRegistry::test_retrieve_tools_returns_fq_ids || exit 1; done
uv run --frozen pytest -q
uv run --frozen ruff check .
git diff --stat
```
