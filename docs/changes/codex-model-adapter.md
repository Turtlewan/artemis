---
spec: codex-model-adapter
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: flash
---

# Spec: codex-model-adapter — reason via Codex on the ChatGPT subscription

**Identity:** Add a `CodexModelPort` ModelPort adapter that performs reasoning via the Codex CLI on the owner's ChatGPT subscription (`codex exec`, read-only sandbox, ephemeral session) and returns `origin="cloud"`. This is the non-sensitive cloud reasoning engine of ADR-022. No `Brain` changes — it plugs in behind the existing `ModelPort` seam.
→ why: ADR-022 (reasoning engine = Codex on the ChatGPT subscription; pluggable, no per-token bill).

<!-- Execution script. 3 files, one phase (the Codex engine). The composite dispatch + fallback that makes the brain USE this is the separate `composite-model-routing` spec; build this first. -->

## Assumptions
- The `codex` CLI is installed (verified: `codex-cli 0.141.0`) and the owner has run `codex login` (subscription auth). This adapter does **not** manage login — if Codex is not authed, `codex exec` exits non-zero and `complete` raises; the `composite-model-routing` spec handles fallback. The composite logs every Codex failure at WARNING as a visible **DEGRADED → local** line, so an expired/revoked subscription surfaces as repeated degraded logs, **not** silent loss of cloud reasoning. → impact: Stop (no login logic here). [apex-security FLAG]
- Verified via `codex exec --help`: `codex exec [PROMPT] -m <model> --sandbox read-only --ephemeral --skip-git-repo-check --color never -o <file>` runs one non-interactive reasoning turn and writes the **final assistant message** to `<file>`. The prompt is read from **stdin** when the trailing arg is `-`. → impact: Stop (the `-o` last-message file is the contract — do NOT scrape prose from stdout).
- `--output-schema <file>` constrains the final response to a JSON Schema (maps to `ModelPort.response_schema`). → impact: Low.
- `ModelPort` (`src/artemis/ports/model.py`) is a `@runtime_checkable` Protocol: `complete`, `complete_stream`, `embed`. `ModelResponse` carries `origin` ("local"|"cloud") and `model_id`. → impact: Stop (`CodexModelPort` must structurally satisfy the Protocol — same signatures, keyword-only where the Protocol is).
- `read-only` sandbox + `--ephemeral` means Codex cannot run shell commands or persist a session — it is a pure reasoning call. → impact: Stop (never use `workspace-write` / `danger-full-access` here).
- Codex exposes no embeddings → `embed` raises `NotImplementedError` (embeddings stay local per ADR-022). → impact: Low.
- `codex exec` does not expose `temperature`/`max_tokens`/token-usage on the `-o` path → those params are accepted but not forwarded; `usage` is `Usage(0,0,0)`. → impact: Low (note in a comment; revisit if `--json` event parsing is added later).
- **`response_schema` is always a compile-time tool schema** (from a registered tool's `args_json_schema()` in the Brain), never user-derived — so no schema size/depth guard is needed. → impact: Stop (if a user-derived schema could ever reach `complete`, add a depth/size guard first). [apex-security FLAG]
- **`_render_prompt` role tags are a known minor injection surface** — owner text could contain a literal `[system]`/`[user]` line. Accepted for the single-owner appliance (the owner is not adversarial to themselves); untrusted *external* content reaches a model only via the DR-a quarantine path, never raw here. → impact: Low. [apex-security FLAG]

## Files to change
1. **create** `src/artemis/adapters/codex_adapter.py` — `CodexModelPort`.
2. **modify** `src/artemis/config.py` — add `codex_binary` + `codex_model` Settings fields; add `"codex"` to the `ModelRole.adapter` Literal.
3. **create** `tests/test_codex_adapter.py` — tests with a faked subprocess (no real Codex call).

## Exact changes

### 1. `src/artemis/adapters/codex_adapter.py` (new)
```python
"""CodexModelPort — reasoning via the Codex CLI on the ChatGPT subscription (ADR-022).

Runs `codex exec` non-interactively in a read-only, ephemeral sandbox (no code
execution, no persisted session) and reads the final assistant message from the
`-o` output file. origin="cloud". No embeddings (raises)."""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from artemis.config import Settings, get_settings
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector

logger = logging.getLogger(__name__)

_ROLE_PREFIX = {"system": "[system]", "user": "[user]", "assistant": "[assistant]"}


def _render_prompt(messages: Sequence[Message]) -> str:
    """Flatten role-tagged messages into one Codex prompt."""
    return "\n\n".join(f"{_ROLE_PREFIX.get(m.role, f'[{m.role}]')}\n{m.content}" for m in messages)


class CodexModelPort:
    """ModelPort adapter that reasons via `codex exec` on the ChatGPT subscription."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings: Settings = settings or get_settings()
        self._binary = self._settings.codex_binary   # typed Settings fields (no getattr bypass)
        self._model = self._settings.codex_model

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,   # not forwarded — codex exec has no such flag
        max_tokens: int | None = None,
    ) -> ModelResponse:
        prompt = _render_prompt(messages)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "last.txt"
            args = [
                self._binary, "exec",
                "-m", self._model,
                "--sandbox", "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color", "never",
                "-o", str(out),
            ]
            if response_schema is not None:
                schema_path = Path(td) / "schema.json"
                await asyncio.to_thread(schema_path.write_text, json.dumps(response_schema))
                args += ["--output-schema", str(schema_path)]
            args.append("-")  # read prompt from stdin

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate(prompt.encode())
            if proc.returncode != 0:
                # SECURITY: stderr may echo prompt fragments (possibly sensitive owner
                # data). Log it at DEBUG in-process only; raise a SCRUBBED message that
                # carries NO prompt text — the composite logs this exception, so it must
                # stay content-free. [apex-security BLOCK]
                logger.debug(
                    "codex exec stderr (rc=%s): %s",
                    proc.returncode, stderr.decode(errors="replace")[:300],
                )
                raise RuntimeError(f"codex exec failed (rc={proc.returncode})")
            text = (
                (await asyncio.to_thread(out.read_text, encoding="utf-8")).strip()
                if out.exists()
                else ""
            )

        return ModelResponse(
            text=text,
            finish_reason="stop",
            usage=Usage(0, 0, 0),
            origin="cloud",
            model_id=self._model,
        )

    def complete_stream(
        self, *, role: str, messages: Sequence[Message], temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """No native token stream on the subscription path — yield the full completion once."""

        async def _one() -> AsyncIterator[str]:
            resp = await self.complete(role=role, messages=messages, temperature=temperature)
            yield resp.text

        return _one()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        raise NotImplementedError("Codex has no embeddings; embeddings stay local (ADR-022).")
```

### 2. `src/artemis/config.py` (modify)
- In the `ModelRole` model, widen the adapter Literal:
  **From:** `adapter: Literal["openai", "claude-cli"]`
  **To:** `adapter: Literal["openai", "claude-cli", "codex"]`
- On `Settings(BaseSettings)`, add two fields (with defaults, so off-the-shelf config still loads):
```python
    codex_binary: str = "codex"
    codex_model: str = "gpt-5.4"
```
Touch nothing else (no roles.toml change in this spec — that is `composite-model-routing`).

### 3. `tests/test_codex_adapter.py` (new)
Cover, with `asyncio.create_subprocess_exec` monkeypatched to a fake that (a) writes the `-o` file from its captured args and (b) returns a configurable `returncode` — never spawning real Codex:
- `_render_prompt` flattens a system+user message with role tags.
- `complete` returns `ModelResponse(text=<file contents>, origin="cloud", model_id="gpt-5.4")` on returncode 0.
- `complete` with `response_schema` writes a `schema.json` and includes `--output-schema` in the args (assert via the captured args).
- `complete` raises `RuntimeError` on returncode != 0, and the message is **scrubbed** — it carries the returncode but NOT the stderr/prompt text (assert the prompt string and the fake stderr are absent from `str(exc)`). [apex-security BLOCK]
- `embed` raises `NotImplementedError`.
- **Protocol conformance:** `isinstance(CodexModelPort(settings), ModelPort)` is `True` (runtime_checkable).

## Acceptance criteria
1. **Protocol conformance** → `uv run --frozen pytest tests/test_codex_adapter.py -q` includes a passing `isinstance(..., ModelPort)` check.
2. **No real Codex spawned** → the test suite passes with `codex` absent from PATH (subprocess is monkeypatched). Verify: run with PATH stripped of codex — still green.
3. **Type gate** → `uv run --frozen mypy` → `Success: no issues found` (CodexModelPort structurally satisfies `ModelPort`; no `type: ignore`).
4. **Lint/format** → `uv run --frozen ruff check .` + `ruff format --check .` clean.
5. **Surgical** → `git diff --stat` shows only the 3 files above.

## Commands to run
```bash
uv sync
uv run --frozen ruff format .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest tests/test_codex_adapter.py -q
uv run --frozen pytest -q   # full suite unchanged
```

## Progress
_(Coding mode writes here — do not edit manually)_
