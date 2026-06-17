"""M1-c HTTP API router — /ask and /ask/stream endpoints.

Mounts on the existing brain FastAPI app. The shared ``Gateway`` is
accessed via ``request.app.state.gateway`` (set in ``main.py`` lifespan).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class AskRequest(BaseModel):
    """A text request to the brain."""

    text: str


class AskResponse(BaseModel):
    """The brain's response to a text request."""

    text: str
    path: str
    tool_used: str | None = None
    escalated: bool = False


@router.post("/ask")
async def ask(request: Request, body: AskRequest) -> AskResponse:
    """Send a text request and receive a complete JSON response."""
    gateway = request.app.state.gateway
    result = await gateway.handle_text(body.text)
    return AskResponse(
        text=result.text,
        path=result.path,
        tool_used=result.tool_used,
        escalated=result.escalated,
    )


@router.post("/ask/stream")
@router.get("/ask/stream")
async def ask_stream(request: Request, text: str | None = None) -> StreamingResponse:
    """Stream a text response via Server-Sent Events.

    Accepts the query via query param ``text`` (GET) or JSON body ``{"text": "..."}`` (POST).
    Yields ``data: <chunk>`` frames followed by a terminal ``data: [DONE]`` frame.
    """
    # Resolve text from query param or POST body
    if request.method == "POST":
        body = await request.json()
        request_text = body.get("text", "")
    elif text is not None:
        request_text = text
    else:
        request_text = ""

    gateway = request.app.state.gateway

    async def event_stream() -> AsyncIterator[str]:
        async for chunk in gateway.handle_text_stream(request_text):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
