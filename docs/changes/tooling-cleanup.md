---
spec: tooling-cleanup
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: flash
---

# Spec: tooling-cleanup — close the VectorStore protocol gap + clear pre-existing ruff format drift

**Identity:** Two mechanical cleanups left over from the validation slice. (1) Widen `InMemoryToolIndex.add` to match the `VectorStore` protocol's already-`Sequence`/`Mapping` signature so the index conforms honestly and the `# type: ignore[assignment]` in the conformance test can be removed. (2) Apply `ruff format` to 5 files carrying pre-existing format drift. No production behaviour change; no Mac/MLX/Mini dependency — buildable on WSL2 now.
→ why: docs/handoff/2026-06-18.md § Decisions Made #1 (protocol gap, owner chose "widen the index") + § What's Next #1 (format drift).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->
<!-- Split rule: 7 distinct files touched but ONE logical phase — Task 2 is a single zero-judgment `ruff format .` command, not per-file logic. Kept as one spec deliberately. -->

## Assumptions
- The `VectorStore` Protocol (`src/artemis/ports/retrieval.py:40-55`) already declares `add(scope: Scope, ids: Sequence[str], vectors: Sequence[Vector], metadata: Sequence[Mapping[str, object]]) -> None`. The gap is that `InMemoryToolIndex.add` narrows these to `list`/`dict`. → impact: Stop (re-read both files before editing; the fix only widens the index, never the protocol).
- `Scope = str` (`src/artemis/ports/types.py:12`), so `InMemoryToolIndex`'s existing `scope: str` already matches the protocol's `scope: Scope` — **do not change the `scope` param.** → impact: Stop (surgical: only `ids`/`vectors`/`metadata` change).
- `[tool.mypy]` sets `strict = true`, which enables `warn_unused_ignores`. Once the index conforms, the `# type: ignore[assignment]` at `tests/test_manifest_registry.py:245` becomes unused and `mypy` will error on it — so removing it is required, not optional. → impact: Stop (this is the acceptance signal for Task 1).
- `InMemoryToolIndex.add`'s body uses only `len()`, `zip()`, iteration, and `dict(meta)` — all valid on `Sequence`/`Mapping` — so the body is unchanged and behaviour is identical. → impact: Low.
- At the live commit, `ruff format --check .` reports exactly 5 files would reformat: `scripts/dev_chat.py`, `src/artemis/knowledge/vector_store.py`, `tests/test_model_auth.py`, `tests/test_offline_compose.py`, `tests/test_vector_store.py`. None overlap the Task 1 files. → impact: Low (run Task 2 after Task 1 so any new drift from Task 1's edit is also caught).

## Files to change
1. **modify** `src/artemis/registry/index.py` — widen the `add` signature to `Sequence`/`Mapping`; add the `collections.abc` import; remove the malformed `# type[ignore]` inline comment.
2. **modify** `tests/test_manifest_registry.py` — remove the now-unused `# type: ignore[assignment]` on line 245.
3. **format-only (no hand-edit)** `scripts/dev_chat.py`, `src/artemis/knowledge/vector_store.py`, `tests/test_model_auth.py`, `tests/test_offline_compose.py`, `tests/test_vector_store.py` — reformatted by `ruff format .` in Task 2.

## Exact changes

### 1. `src/artemis/registry/index.py` — widen `add` to satisfy `VectorStore`

Add the `collections.abc` import alongside the existing imports (keep the existing `from artemis.ports.types import ...` line as-is):
```python
from collections.abc import Mapping, Sequence
```

Replace the `add` signature (lines 33-39). **From:**
```python
    def add(
        self,
        scope: str,
        ids: list[str],  # type[ignore] — Sequence[str] vs list[str]
        vectors: list[Vector],
        metadata: list[dict[str, object]],
    ) -> None:
```
**To:**
```python
    def add(
        self,
        scope: str,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
```
Leave the entire method body (lines 40-52) and every other method unchanged. Leave the `scope: str` param unchanged (`Scope = str`).

### 2. `tests/test_manifest_registry.py` — drop the unused ignore

Line 245. **From:**
```python
        vs: VectorStore = index  # type: ignore[assignment]
```
**To:**
```python
        vs: VectorStore = index
```
Touch nothing else in the file.

### 3. Format drift — Task 2 command only

No hand-edits. The `ruff format .` command in Task 2 reformats the 5 drift files. Do not manually edit them.

## Acceptance criteria
1. **Index conforms, ignore removed** → run `uv run --frozen mypy` → `Success: no issues found` (no `unused-ignore` error, no `assignment` error). Verify: the diff of `tests/test_manifest_registry.py` shows the `# type: ignore[assignment]` comment removed from line 245.
2. **Behaviour unchanged** → run `uv run --frozen pytest -q` → `121 passed` (same as the live baseline).
3. **Format drift cleared** → run `uv run --frozen ruff format --check .` → `44 files already formatted` (0 would reformat).
4. **Lint still clean** → run `uv run --frozen ruff check .` → `All checks passed`.
5. **Scope is surgical** → `git diff --stat` shows only the 7 files above changed; `src/artemis/registry/index.py` shows only the import line + 3 param-type changes + the removed comment.

## Commands to run
```bash
uv sync --all-extras
# Task 1 edits (index.py + test_manifest_registry.py), then:
uv run --frozen ruff format .          # Task 2
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
uv run --frozen pytest -q
```
