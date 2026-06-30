---
slice: client-revival
status: ready
coder_effort: high
---

# CR-3 — Ask (the client's Ask popup talks to the live brain)

**Identity:** Third client-revival slice — implement `/app/ask`, `/app/ask/stream`, `/app/ask/voice` backed by the v2 `QuotaAwareRouter`, matching the client's exact wire + SSE contract. After this, the Ask-Artemis popup gets real answers from the subscription-first model chain. A chat Ask is a single completion (not a plan→act→verify task), so it goes **straight through the model router**, not the Spine. Voice is deferred (Tier 5) — `/app/ask/voice` returns a graceful "not yet available" over the same SSE shape.

## Files to change

1. `src/artemis/api/ask_routes.py` — **create**: `AskRequest`/`AskResponse` models (v1-exact) + an `APIRouter` with the three ask routes.
2. `src/artemis/api/app.py` — **modify**: add a `model: ModelPort | None = None` param to `create_app`, compose the router onto `app.state`, include the ask router. Leave auth wiring + `/healthz` + `/app/status` unchanged.
3. `tests/test_api_ask.py` — **create**: ask (non-stream) returns text+engine tag; stream yields SSE text frames + `[DONE]`; voice returns the deferred message; all require a session (via `dependency_overrides`).

One cohesive "ask" vertical → a single logical phase.

## Exact changes

### Wire contract (v1-exact — from `docs/findings/client-brain-contract-2026-06-30.md`)
- `AskRequest`: `{ text: str, speak: bool = False }`.
- `AskResponse`: `{ text: str, path: str, tool_used: str | None = None, escalated: bool = False }`.
- SSE (`/app/ask/stream`, `/app/ask/voice`): `media_type="text/event-stream"`; emit the answer as standard SSE `data:` lines then `data: [DONE]\n\n`. The client's Rust `parse_stream_frame` turns each non-`[DONE]`/non-error frame into a `Text` event and `[DONE]` into the terminal `Done` event. (No `vault_locked` frames — no-lock.)

### `src/artemis/api/ask_routes.py`
```python
"""Ask routes: chat Q&A backed by the subscription-first model router."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from artemis.api.auth import Principal, require_session
from artemis.ports.model import ModelPort
from artemis.types import Message

_SYSTEM = "You are Artemis, the owner's personal assistant. Answer concisely and helpfully."


class AskRequest(BaseModel):
    text: str
    speak: bool = False


class AskResponse(BaseModel):
    text: str
    path: str
    tool_used: str | None = None
    escalated: bool = False


def _engine_tag(model_id: str) -> str:
    """Map the serving backend's model id to the client's engine tag (local|codex|review)."""
    lowered = model_id.lower()
    if "gpt" in lowered or "codex" in lowered:
        return "codex"
    return "local"


def _sse_event(text: str) -> str:
    """Encode possibly-multiline text as one SSE data event (each line prefixed `data:`)."""
    return "".join(f"data: {line}\n" for line in text.split("\n")) + "\n"


def _router(request: Request) -> ModelPort:
    model: ModelPort = request.app.state.model
    return model


async def _answer(model: ModelPort, text: str) -> tuple[str, str]:
    resp = await model.complete(
        messages=[Message(role="system", content=_SYSTEM), Message(role="user", content=text)]
    )
    return resp.text, _engine_tag(resp.model_id)


router = APIRouter(prefix="/app")


@router.post("/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    _principal: Principal = Depends(require_session),
    model: ModelPort = Depends(_router),
) -> AskResponse:
    answer, path = await _answer(model, req.text)
    return AskResponse(text=answer, path=path, tool_used=None, escalated=False)


@router.post("/ask/stream")
async def ask_stream(
    req: AskRequest,
    _principal: Principal = Depends(require_session),
    model: ModelPort = Depends(_router),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        answer, _path = await _answer(model, req.text)
        yield _sse_event(answer)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/ask/voice")
async def ask_voice(
    req: AskRequest,
    _principal: Principal = Depends(require_session),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        yield _sse_event("Voice answers aren't available yet.")
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

Notes for the coder:
- `Principal` and `require_session` come from CR-2's `src/artemis/api/auth.py` (already present). Match the actual symbol names there; if `require_session` needs the request/app.state, use it exactly as the auth routes do.
- The router instance is read from `request.app.state.model` — set up in `create_app` (next).
- The v2 `QuotaAwareRouter` implements `ModelPort.complete` and returns a `ModelResponse` with `.text` and `.model_id`. It does not token-stream, so the stream emits the full answer as one SSE event then `[DONE]` — that's expected for CR-3 (true token streaming is a later refinement).

### `src/artemis/api/app.py` — compose the router + include ask routes
- Add `model: ModelPort | None = None` to `create_app(...)`. After building the auth components, set `app.state.model = model if model is not None else build_model_router()` (import `build_model_router` from `artemis.model.compose` and `ModelPort` from `artemis.ports.model`).
- `app.include_router(ask_routes.router)` (import the ask router).
- Do not change auth wiring, `/healthz`, or `/app/status`.

### `tests/test_api_ask.py`
Use `dependency_overrides[require_session]` to bypass the handshake, and inject a fake model via `create_app(model=FakeModel(...))`. (Reuse the `FakeModel` shape from `tests/test_app.py`.)

```python
"""Tests for the ask routes."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, text: str = "hello there", model_id: str = "qwen3:4b") -> None:
        self._text = text
        self._model_id = model_id

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, model, response_schema, temperature, max_tokens
        return ModelResponse(
            text=self._text,
            model_id=self._model_id,
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def _client(model: FakeModel) -> TestClient:
    app = create_app(model=model)
    app.dependency_overrides[require_session] = lambda: Principal(device_id="dev", person_id="owner")
    return TestClient(app)


def test_ask_returns_text_and_engine_tag() -> None:
    client = _client(FakeModel("the answer", "qwen3:4b"))
    resp = client.post("/app/ask", json={"text": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "the answer"
    assert body["path"] == "local"
    assert body["escalated"] is False


def test_ask_codex_engine_tag() -> None:
    client = _client(FakeModel("x", "gpt-5.5"))
    assert client.post("/app/ask", json={"text": "hi"}).json()["path"] == "codex"


def test_ask_stream_emits_text_then_done() -> None:
    client = _client(FakeModel("line one\nline two"))
    resp = client.post("/app/ask/stream", json={"text": "hi"})
    assert resp.status_code == 200
    body = resp.text
    assert "data: line one" in body
    assert "data: line two" in body
    assert body.rstrip().endswith("data: [DONE]")


def test_ask_voice_deferred_message() -> None:
    client = _client(FakeModel())
    resp = client.post("/app/ask/voice", json={"text": "hi", "speak": True})
    assert resp.status_code == 200
    assert "aren't available yet" in resp.text
    assert "data: [DONE]" in resp.text


def test_ask_requires_session() -> None:
    # No dependency override -> real require_session -> 401 without a bearer.
    client = TestClient(create_app(model=FakeModel()))
    assert client.post("/app/ask", json={"text": "hi"}).status_code == 401
```

Notes:
- If `Principal`'s constructor fields differ from `(device_id=..., person_id=...)`, match the real dataclass in `auth.py`.
- `test_ask_requires_session` uses no override, so the real `require_session` rejects the unauthenticated call with 401.

## Acceptance criteria

1. `POST /app/ask` (authenticated) → `200 {text, path, tool_used:null, escalated:false}`; `path` = `local` for an ollama model id, `codex` for a gpt/codex id → `test_ask_returns_text_and_engine_tag` + `test_ask_codex_engine_tag` pass.
2. `POST /app/ask/stream` → `text/event-stream` emitting the answer as `data:` lines then `data: [DONE]` → `test_ask_stream_emits_text_then_done` passes.
3. `POST /app/ask/voice` → SSE with the deferred-voice message + `[DONE]` → `test_ask_voice_deferred_message` passes.
4. All ask routes require a session (`401` without a bearer) → `test_ask_requires_session` passes.
5. `create_app(model=...)` injects a model; default composes the real `QuotaAwareRouter`.
6. Full-project verify green: `uv run mypy` (strict) + `uv run pytest -q` + `uv run ruff check` + `uv run ruff format --check`.

## Commands to run

```bash
uv run ruff format src/artemis/api tests/test_api_ask.py
uv run ruff check src/artemis/api tests/test_api_ask.py
uv run mypy
uv run pytest -q
```
