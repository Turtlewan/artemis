---
spec: dev-model-auth
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: flash
---

# Spec: dev-model-auth — Bearer-auth header on the OpenAI-compatible adapters

**Identity:** Adds an optional `ARTEMIS_MODEL_API_KEY` setting and sends it as `Authorization: Bearer <key>` from `OpenAIModelPort` + `OpenAIEmbeddingModel`, so the as-built adapters (today: no auth header, built for the Mini's local no-auth MLX server) can also reach an **authed** OpenAI-compatible endpoint (DeepSeek cloud, OpenAI, etc.) in a pre-Mini WSL2 dev session. Local MLX/Ollama keep working (no key set → no header).
→ why: validation-slice "dev-runnable brain" enabler (status.md Open Question 2026-06-17; the decided Tier-2 config = DeepSeek responder + FakeEmbedder). Pairs with `dev-offline-compose`.

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->
<!-- Split rule: ONE phase (auth header) across 1 modify (config.py) + 1 modify (model_adapters.py) + 1 create (test). Within the 3-file limit. The `dev-offline-compose` spec is the independent companion (compose_brain overrides + FakeEmbedder). -->

## Assumptions
- Slice 1 is built: `src/artemis/config.py` defines `Settings(BaseSettings)` with `env_prefix="ARTEMIS_"`; `src/artemis/adapters/model_adapters.py` defines `OpenAIModelPort` + `OpenAIEmbeddingModel`, each building its own `httpx.AsyncClient` with no headers. → impact: Stop (verified against current code 2026-06-17).
- The adapters POST to an **absolute** role-endpoint URL (`f"{base_url}/chat/completions"` / `f"{endpoint}/embeddings"`), so the client `base_url="http://127.0.0.1"` is overridden per request; only the **headers** carried by the client (and the streaming client) matter for auth. → impact: Stop (header must be set on every client the adapter constructs, including the per-call streaming client inside `complete_stream`).
- `model_api_key` is a **secret**: declare it `exclude=True` so it never appears in `model_dump()`/serialisation. It is NOT written to any file by this spec — it is read from the process env (`ARTEMIS_MODEL_API_KEY`) only. → impact: Caution (secret hygiene).
- `pytest` runs from the repo root with `asyncio_mode=auto`; `config/roles.toml` (has a `responder` role, `adapter="openai"`) and `config/.env.dev` exist and load via the `Settings` validators. → impact: Low (tests construct `Settings(...)` directly).

## Files to change
1. **modify** `src/artemis/config.py` — add the `model_api_key` field.
2. **modify** `src/artemis/adapters/model_adapters.py` — add `_auth_headers()` helper; apply to all three client constructions.
3. **create** `tests/test_model_auth.py` — unit + on-the-wire (MockTransport) coverage.

## Exact changes

### 1. `src/artemis/config.py`
Add the field inside `Settings`, immediately after the existing `embedding_dimension` field (before `roles`):
```python
    # Optional API key for authed OpenAI-compatible endpoints (dev: DeepSeek/OpenAI
    # cloud). Local MLX/Ollama servers need none. Sent as `Authorization: Bearer`.
    # Secret: read from ARTEMIS_MODEL_API_KEY, excluded from serialisation.
    model_api_key: str | None = Field(default=None, exclude=True)
```
(`Field` is already imported.)

### 2. `src/artemis/adapters/model_adapters.py`
Add a module-level helper after the imports (below the existing `from artemis.ports.types import ...` line):
```python
def _auth_headers(settings: Any) -> dict[str, str]:
    """Bearer auth header for authed OpenAI-compatible endpoints.

    Empty dict for local no-auth servers (MLX/Ollama) — no key configured.
    """
    key = getattr(settings, "model_api_key", None)
    return {"Authorization": f"Bearer {key}"} if key else {}
```

In `OpenAIModelPort.__init__`, replace the client construction:
```python
        self._client = httpx.AsyncClient(
            base_url="http://127.0.0.1",
            timeout=60.0,
            headers=_auth_headers(self._settings),
        )
```

In `OpenAIModelPort.complete_stream`'s inner `_stream()`, replace the streaming client construction:
```python
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1",
                timeout=120.0,
                headers=_auth_headers(self._settings),
            ) as client:
```

In `OpenAIEmbeddingModel.__init__`, replace the client construction:
```python
        self._client = httpx.AsyncClient(
            base_url="http://127.0.0.1",
            timeout=30.0,
            headers=_auth_headers(self._settings),
        )
```

### 3. `tests/test_model_auth.py` (new)
```python
"""Bearer-auth header coverage for the OpenAI-compatible adapters."""

from __future__ import annotations

import httpx

from artemis.adapters.model_adapters import OpenAIModelPort, _auth_headers
from artemis.config import Settings
from artemis.ports.types import Message


def test_auth_headers_present_when_key_set() -> None:
    assert _auth_headers(Settings(model_api_key="sk-test")) == {
        "Authorization": "Bearer sk-test"
    }


def test_auth_headers_absent_when_no_key() -> None:
    assert _auth_headers(Settings()) == {}


def test_model_port_client_carries_bearer() -> None:
    port = OpenAIModelPort(Settings(model_api_key="sk-test"))
    assert port._client.headers["authorization"] == "Bearer sk-test"


async def test_complete_sends_bearer_on_wire() -> None:
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    port = OpenAIModelPort(Settings(model_api_key="sk-test"))
    # Keep the adapter-built auth headers; swap only the transport.
    port._client = httpx.AsyncClient(
        base_url="http://127.0.0.1",
        transport=httpx.MockTransport(handler),
        headers=port._client.headers,
    )
    resp = await port.complete(role="responder", messages=[Message(role="user", content="hi")])
    assert resp.text == "ok"
    assert captured["auth"] == "Bearer sk-test"
```

## Acceptance criteria
1. Key set → header built → `uv run pytest tests/test_model_auth.py -q` passes (4 tests; covers helper, no-key, client header, on-the-wire).
2. No-key path unchanged → `uv run pytest -q` still green (all prior tests pass; local no-auth adapters send no `Authorization`).
3. Types/lint clean → `uv run mypy src` and `uv run ruff check src tests` report no new errors.

## Commands to run
```bash
uv run pytest tests/test_model_auth.py -q
uv run pytest -q
uv run mypy src
uv run ruff check src tests
```
