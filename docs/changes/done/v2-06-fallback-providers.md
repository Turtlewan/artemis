# v2-06 · Metered + local fallback providers (chain capstone)

status: ready
slice: 1 (widen model layer) — part 2 of 2 (follows `v2-05`)
coder: codex
coder_effort: high
autonomy: L5

## Identity

Complete the four-provider chain: add an `AnthropicAPIProvider` (metered Anthropic Messages API,
official `anthropic` SDK) and an `OllamaProvider` (local, `httpx` to `localhost:11434`), then a
`compose.build_model_router()` capstone that assembles the subscription-first chain
`codex → claude-code → anthropic-api → ollama`, each behind its own `ModelClient` with the correct
per-backend default model. Design home: `docs/v2/architecture.md` §2 (routing policy: "other sub →
metered API → local") + §3 layer 1.

## Prerequisites

`v2-05` (router, errors, cli_support, ClaudeCodeProvider) — committed `2e8b39e`.

## Files to change

| File | Op | What |
|---|---|---|
| `pyproject.toml` | modify | add runtime deps `anthropic>=0.40` and `httpx>=0.27` |
| `src/artemis/model/anthropic_provider.py` | create | `RawProvider` over the Anthropic Messages API (async SDK) |
| `src/artemis/model/ollama_provider.py` | create | `RawProvider` over the local Ollama chat API (async httpx) |
| `src/artemis/model/compose.py` | create | `build_model_router()` — assemble the 4-backend chain |
| `src/artemis/model/__init__.py` | modify | export the two providers + `build_model_router` |
| `tests/model/test_anthropic_provider.py` | create | structured extract · 429→quota · missing-key→unavailable (SDK mocked) |
| `tests/model/test_ollama_provider.py` | create | structured extract · conn-refused→unavailable (httpx mocked) |
| `tests/model/test_compose.py` | create | 4-backend chain order + fallover with provider classes (boundaries mocked) |

> Scope lock: do **not** modify `router.py`, `errors.py`, `cli_support.py`, `client.py`,
> `codex_provider.py`, `claude_code_provider.py`, `ports/`, `spine/`, or `capabilities/`. Reuse the
> v2-05 error types and `ModelClient` unchanged. No live network/Ollama calls in any test.

## Exact changes

### 1. `pyproject.toml`
Add to `[project] dependencies`: `"anthropic>=0.40"`, `"httpx>=0.27"`. Run `uv sync` (normal user).
Package legitimacy: both are the official, actively-maintained PyPI packages — no typosquat risk.

### 2. `model/anthropic_provider.py` (create)
`RawProvider` over the Anthropic Messages API using `anthropic.AsyncAnthropic`. Structured output
uses Anthropic's tool pattern (the canonical schema becomes a tool `input_schema`):
```python
class AnthropicAPIProvider:  # implements RawProvider
    def __init__(self, *, api_key: str | None = None, model_default: str = "claude-sonnet-4-6",
                 max_tokens: int = 4096, client: AsyncAnthropic | None = None) -> None:
        # resolve key from arg or env ANTHROPIC_API_KEY; if absent AND no injected client →
        # store None and raise ProviderUnavailableError("anthropic_api", "no API key") on generate()
        ...

    async def generate(self, *, messages, model, schema) -> str:
        # map artemis Messages → anthropic messages; a role=="system" message → the top-level
        #   `system` param (Anthropic has no system role in the messages array).
        # try: response = await client.messages.create(model=model or default, max_tokens=...,
        #        system=system_text or NOT_GIVEN, messages=mapped,
        #        tools=[{"name":"emit","description":"Return the result.","input_schema":schema}] if schema else NOT_GIVEN,
        #        tool_choice={"type":"tool","name":"emit"} if schema else NOT_GIVEN)
        # schema path → find the tool_use block named "emit", return json.dumps(block.input)
        # no-schema path → concatenate text blocks, return that
        # except anthropic.RateLimitError (or status 429) → QuotaExhaustedError("anthropic_api", ...)
        # except anthropic.AuthenticationError / APIConnectionError → ProviderUnavailableError(...)
```
- Use `anthropic` typed exceptions for classification; fall back to `cli_support.is_quota_signal(str(exc))`
  only if the exception type is ambiguous. Keep imports of `anthropic` at module top (it is now a dep).
- The provider returns a JSON **string** (the tool input serialized); `ModelClient` validates it against
  the canonical schema and re-asks on mismatch — same contract as the other providers.

### 3. `model/ollama_provider.py` (create)
`RawProvider` over `POST http://localhost:11434/api/chat` via `httpx.AsyncClient`:
```python
class OllamaProvider:  # implements RawProvider
    def __init__(self, *, base_url: str = "http://localhost:11434", model_default: str = "qwen3:4b",
                 timeout: float = 120.0) -> None: ...

    async def generate(self, *, messages, model, schema) -> str:
        body = {"model": model or default, "stream": False,
                "messages": [{"role": m.role, "content": m.content} for m in messages]}
        if schema is not None:
            body["format"] = to_ollama_schema(schema)   # Ollama lenient structured output
        try:
            resp = await client.post(f"{base_url}/api/chat", json=body, timeout=timeout)
            resp.raise_for_status()
        except httpx.ConnectError / httpx.ConnectTimeout → ProviderUnavailableError("ollama", ...)
        except httpx.HTTPStatusError as e:  # 429 → quota (rare locally); else unavailable
            QuotaExhaustedError if e.response.status_code == 429 else ProviderUnavailableError
        return resp.json()["message"]["content"]   # already JSON text when format was set
```
- Ollama has no real quota; the 429 branch is defensive. Connection failure (server down) is the
  expected fallover path → `ProviderUnavailableError`. Import `to_ollama_schema` from `schema_norm`.

### 4. `model/compose.py` (create)
```python
def build_model_router(*, anthropic_api_key: str | None = None,
                       enable_ollama: bool = True) -> QuotaAwareRouter:
    """Assemble the subscription-first chain: codex → claude-code → anthropic-api → ollama.
    Each backend is a ModelClient wrapping one RawProvider with that backend's default model."""
    backends: list[tuple[str, ModelPort]] = [
        ("codex",       ModelClient(CodexProvider(),       model_default="gpt-5.5")),
        ("claude_code", ModelClient(ClaudeCodeProvider(),  model_default="sonnet")),
        ("anthropic_api", ModelClient(AnthropicAPIProvider(api_key=anthropic_api_key),
                                      model_default="claude-sonnet-4-6")),
    ]
    if enable_ollama:
        backends.append(("ollama", ModelClient(OllamaProvider(), model_default="qwen3:4b")))
    return QuotaAwareRouter(backends)
```
- This resolves the v2-05 wiring note: each `ModelClient` carries the right `model_default`, so a
  `model=None` call from the spine reaches each backend with a valid model id for that backend.

### 5. `model/__init__.py` (modify)
Add exports: `AnthropicAPIProvider`, `OllamaProvider`, `build_model_router`.

## Acceptance criteria

1. **Anthropic structured extract:** with a mocked `AsyncAnthropic` whose `messages.create` returns a
   `tool_use` block `{"input": {"answer": "ok"}}`, `provider.generate(schema=...)` returns
   `'{"answer": "ok"}'` (order-insensitive JSON equality).
   → `uv run pytest tests/model/test_anthropic_provider.py -q`
2. **Anthropic classification:** a mocked `RateLimitError` → `QuotaExhaustedError`; provider built with
   no key and no client → `ProviderUnavailableError` on `generate`.
3. **Ollama structured extract:** mocked httpx returns `{"message":{"content":"{\"answer\":\"ok\"}"}}`
   → `generate` returns that content string; the request body carried `format` when a schema was passed.
4. **Ollama fallover:** mocked `httpx.ConnectError` → `ProviderUnavailableError`.
5. **Chain capstone:** `build_model_router(...)` returns a `QuotaAwareRouter` whose backend names are
   `["codex","claude_code","anthropic_api","ollama"]` in order; with the codex + claude_code + anthropic
   boundaries mocked to raise `QuotaExhaustedError` and the ollama boundary mocked to return a valid
   `ModelResponse`, `router.complete(...)` returns the ollama result. (Mock at each provider's
   external boundary — subprocess / SDK / httpx — never a live call.)
6. **Green (full host-verify):** `uv run mypy` (strict, 0 errors over all src+tests) + `uv run pytest -q`
   (all pass, ≥42 prior + new) + `uv run ruff check src tests` + `uv run ruff format --check src tests`.

## Commands to run
```bash
uv sync
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```
