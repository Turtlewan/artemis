# v2-05 · Model router seam + Claude-Code provider

status: ready
slice: 1 (widen model layer) — part 1 of 2 (`v2-06` adds Anthropic-API + Ollama fallbacks)
coder: codex
autonomy: L5

## Identity

Replace the single-provider `ModelClient` direct path with a quota-aware router over multiple
`RawProvider` backends, each owning its own schema down-conversion, and add a `ClaudeCodeProvider`
(`claude -p`). The `QuotaAwareRouter` implements `ModelPort`, so the spine is untouched.
Design home: `docs/v2/architecture.md` §2 (model-layer row, LiteLLM reversed → own router) + §3 layer 1.

## Files to change

| File | Op | What |
|---|---|---|
| `src/artemis/model/errors.py` | create | failover-eligible provider error types |
| `src/artemis/model/cli_support.py` | create | shared CLI helpers (render messages, run subprocess, quota detection) |
| `src/artemis/model/codex_provider.py` | modify | down-convert schema internally; classify quota errors via `cli_support` |
| `src/artemis/model/claude_code_provider.py` | create | `RawProvider` over `claude -p --output-format json` |
| `src/artemis/model/client.py` | modify | stop pre-strictifying; pass canonical schema to the provider |
| `src/artemis/model/router.py` | create | `QuotaAwareRouter` (implements `ModelPort`) — ordered subscription-first fallover |
| `src/artemis/model/__init__.py` | modify | export the new public symbols |
| `tests/model/test_router.py` | create | fallover + exhaustion + first-success (acceptance) |
| `tests/model/test_claude_code_provider.py` | create | argv, JSON-envelope parse, quota detection |
| `tests/model/test_codex_provider.py` | modify/create | quota-detection + internal-strictify unit tests |

> Scope lock: do **not** touch `spine/`, `capabilities/`, `ports/`, or `schema_norm.py` beyond what is
> listed. The `ModelPort` protocol signature in `ports/model.py` is **frozen** — the router conforms to it.

## Exact changes

### 1. `model/errors.py` (create)
```python
"""Provider error taxonomy. Failover-eligible errors signal the router to try the next backend."""
from __future__ import annotations


class ProviderError(RuntimeError):
    """Base for all model-provider failures."""


class FailoverEligibleError(ProviderError):
    """A backend-level failure the router should recover from by trying the next backend."""

    def __init__(self, provider: str, detail: str) -> None:
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider}: {detail}")


class QuotaExhaustedError(FailoverEligibleError):
    """The backend hit a rate / weekly-quota / usage limit."""


class ProviderUnavailableError(FailoverEligibleError):
    """The backend is unreachable or misconfigured (binary missing, connection refused, auth)."""


class AllBackendsExhaustedError(ProviderError):
    """Every backend in the router chain failed over."""

    def __init__(self, failures: list[tuple[str, ProviderError]]) -> None:
        self.failures = failures
        names = ", ".join(name for name, _ in failures) or "(none)"
        super().__init__(f"All backends exhausted: {names}")
```

### 2. `model/cli_support.py` (create)
Shared helpers for CLI-subprocess providers (used by Codex + Claude-Code):
```python
"""Shared subprocess helpers for CLI-backed providers."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence

from artemis.types import Message

_QUOTA_RE = re.compile(
    r"(rate.?limit|quota|usage limit|weekly limit|too many requests|\b429\b|exceeded.*limit"
    r"|limit.*reached)",
    re.IGNORECASE,
)


def render_messages(messages: Sequence[Message]) -> str:
    return "\n\n".join(f"{m.role.upper()}:\n{m.content}" for m in messages)


def is_quota_signal(text: str) -> bool:
    return bool(_QUOTA_RE.search(text))


async def run_cli(argv: list[str], *, stdin: bytes) -> tuple[int, bytes, bytes]:
    """Run argv, feed stdin, return (returncode, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(stdin)
    return (process.returncode or 0, stdout, stderr)
```

### 3. `model/codex_provider.py` (modify)
- `generate`: when `schema is not None`, call `to_strict_schema(schema)` **inside the provider** before
  writing the schema file (move the strictify here from `ModelClient`). Import `to_strict_schema`.
- Replace the local `_render_messages` with `cli_support.render_messages`.
- Error classification: on non-zero exit, if `cli_support.is_quota_signal(stderr_text)` →
  raise `QuotaExhaustedError("codex", excerpt)`; else keep raising the existing `CodexProviderError`
  (a real, non-failover bug — must surface, not be masked).
- Keep `RawProvider` protocol where it is (or move it into `cli_support`/`ports` — author's choice, but
  if moved, update all importers). Default: leave `RawProvider` in `codex_provider.py` to stay surgical.

### 4. `model/claude_code_provider.py` (create)
`RawProvider` impl over the Claude Code CLI:
```python
class ClaudeCodeProvider:  # implements RawProvider
    def __init__(self, *, binary: str = "claude", model_default: str = "sonnet") -> None:
        self._binary = shutil.which(binary) or binary
        self._model_default = model_default

    async def generate(self, *, messages, model, schema) -> str:
        prompt = cli_support.render_messages(messages)
        if schema is not None:
            prompt += "\n\nReturn ONLY a JSON value conforming to this JSON Schema:\n" + json.dumps(schema)
        argv = [self._binary, "-p", prompt, "--output-format", "json",
                "--model", model or self._model_default]
        rc, stdout, stderr = await cli_support.run_cli(argv, stdin=b"")
        text = stdout.decode("utf-8", errors="replace")
        if rc != 0:
            if cli_support.is_quota_signal(stderr.decode("utf-8", "replace") + text):
                raise QuotaExhaustedError("claude_code", _excerpt(stderr))
            raise ProviderUnavailableError("claude_code", _excerpt(stderr))
        return _extract_result(text)  # parse {"result": "..."} envelope; fall back to raw stdout
```
- `_extract_result`: `json.loads(stdout)`; if it is a dict with a `"result"` string key, return that;
  otherwise return the raw stdout stripped. (Tolerates CLI envelope-format drift.)
- Schema is injected into the prompt (the CLI has no native strict-schema flag); the `ModelClient`
  validate-and-re-ask loop enforces conformance — that is why this provider does **not** itself validate.

### 5. `model/client.py` (modify)
- Remove the `to_strict_schema(response_schema)` call and the `strict_schema` local. Pass the **canonical**
  `response_schema` to `self._provider.generate(..., schema=response_schema)` — each provider now owns its
  own down-conversion. The client keeps the `jsonschema.validate(..., schema=response_schema)` +
  re-ask loop unchanged (still validates against the canonical schema).
- Drop the now-unused `to_strict_schema` import.

### 6. `model/router.py` (create)
```python
class QuotaAwareRouter:  # implements ModelPort
    """Try backends in order (subscription-first); fail over on FailoverEligibleError."""

    def __init__(self, backends: Sequence[tuple[str, ModelPort]]) -> None:
        if not backends:
            raise ValueError("QuotaAwareRouter needs at least one backend")
        self._backends = list(backends)

    async def complete(self, *, messages, model=None, response_schema=None,
                       temperature=0.7, max_tokens=None) -> ModelResponse:
        failures: list[tuple[str, ProviderError]] = []
        for name, backend in self._backends:
            try:
                return await backend.complete(
                    messages=messages, model=model, response_schema=response_schema,
                    temperature=temperature, max_tokens=max_tokens,
                )
            except FailoverEligibleError as exc:
                failures.append((name, exc))
                continue
        raise AllBackendsExhaustedError(failures)
```
- Only `FailoverEligibleError` (quota / unavailable) triggers fallover. `ModelOutputError` and other
  exceptions propagate (a backend that connects but can't produce valid output is a real failure, not a
  reason to silently spend the next subscription). No cooldown/budget state in this slice — deferred.

### 7. `model/__init__.py` (modify)
Export: `ModelClient`, `CodexProvider`, `ClaudeCodeProvider`, `QuotaAwareRouter`,
`QuotaExhaustedError`, `ProviderUnavailableError`, `AllBackendsExhaustedError`, `ModelOutputError`.

## Acceptance criteria

1. **Fallover (the slice acceptance):** a `QuotaAwareRouter` over `[("codex", fake_a), ("claude", fake_b)]`
   where `fake_a.complete` raises `QuotaExhaustedError` and `fake_b.complete` returns a valid
   `ModelResponse` → `router.complete(...)` returns `fake_b`'s response, and `fake_b` was called exactly once.
   → `uv run pytest tests/model/test_router.py -q`
2. **First-success short-circuits:** with `fake_a` succeeding, `fake_b.complete` is never awaited.
3. **All exhausted:** both fakes raise `QuotaExhaustedError` → router raises `AllBackendsExhaustedError`
   whose `.failures` lists both backend names.
4. **Quota classification:** `cli_support.is_quota_signal("Claude usage limit reached")` is `True`;
   `is_quota_signal("file not found")` is `False`. Codex provider raises `QuotaExhaustedError` when the
   stubbed subprocess exits non-zero with a quota stderr, and `CodexProviderError` otherwise.
5. **Claude provider:** `_extract_result('{"result":"hi"}')` → `"hi"`; non-JSON stdout → stripped raw.
   argv contains `-p`, `--output-format`, `json`. (Subprocess mocked — no live call.)
6. **No spine regression:** `Spine` still type-checks against `ModelPort`; a `QuotaAwareRouter` is a valid
   `model=` argument to `Spine` (a `tests/` assertion or a mypy-level check).
7. **Green:** full `uv run mypy` (strict, 0 errors) + `uv run pytest -q` (all pass, including the prior 30).

## Commands to run
```bash
uv run mypy
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```
