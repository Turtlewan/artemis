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
