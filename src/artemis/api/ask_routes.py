"""Ask routes: chat Q&A backed by the subscription-first model router."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from artemis.api.auth import Principal, require_session
from artemis.capabilities.fetch_sandbox import FetchSandbox
from artemis.capabilities.invoke import InvokeState, build_invoke_proposal, confirm_invoke
from artemis.capabilities.select import CapabilitySelector
from artemis.capabilities.store import FileCapabilityStore
from artemis.intent import IntentRouter
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.ports.model import ModelPort
from artemis.ports.secrets import SecretStorePort
from artemis.reachout.web_tool import build_web_tool
from artemis.types import Message

_SYSTEM = "You are Artemis, the owner's personal assistant. Answer concisely and helpfully."
_NO_SEARCH_PREFIX = "(couldn't search; answering directly) "
_BUILD_SIGNAL = "Opening build mode for that capability request."
_AGGREGATE_SIGNAL = (
    "Deep research is not available yet. Ask a direct question meanwhile and I can answer it."
)


class AskRequest(BaseModel):
    text: str
    speak: bool = False


class AskResponse(BaseModel):
    text: str
    path: str
    tool_used: str | None = None
    escalated: bool = False
    invoke_id: str | None = None
    capability: str | None = None
    egress_domains: list[str] | None = None
    secrets: list[str] | None = None
    args: dict[str, object] | None = None
    missing: list[str] | None = None


class InvokeConfirmResponse(BaseModel):
    invoke_id: str
    status: Literal["ok", "missing_secrets", "not_found", "error"]
    text: str | None = None
    missing_secrets: list[str] = Field(default_factory=list)


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


def _intent(request: Request) -> IntentRouter:
    # Dedicated Haiku-capable claude_code port — NOT the shared QuotaAwareRouter. Forcing
    # model="haiku" onto the codex-primary router would reach Codex as an unknown model, fail
    # non-failover-eligibly, and silently degrade every classification to plain_ask. Mirrors
    # web_tool.py's reader construction.
    return IntentRouter(ModelClient(ClaudeCodeProvider(), model_default="haiku"))


def _selector(request: Request) -> CapabilitySelector:
    selector: CapabilitySelector = request.app.state.capability_selector
    return selector


def _capability_store(request: Request) -> FileCapabilityStore:
    store: FileCapabilityStore = request.app.state.capability_store
    return store


def _secrets(request: Request) -> SecretStorePort:
    store: SecretStorePort = request.app.state.secrets
    return store


def _fetch_sandbox(request: Request) -> FetchSandbox:
    sandbox: FetchSandbox = request.app.state.fetch_sandbox
    return sandbox


def _quarantine_reader(request: Request) -> ModelPort:
    del request
    return ModelClient(ClaudeCodeProvider(), model_default="haiku")


def _invokes(request: Request) -> dict[str, InvokeState]:
    invokes: dict[str, InvokeState] = request.app.state.invokes
    return invokes


async def _answer(model: ModelPort, text: str) -> tuple[str, str]:
    resp = await model.complete(
        messages=[Message(role="system", content=_SYSTEM), Message(role="user", content=text)]
    )
    return resp.text, _engine_tag(resp.model_id)


async def _routed_answer(model: ModelPort, intent_router: IntentRouter, text: str) -> AskResponse:
    intent = await intent_router.classify(text)
    if intent.route == "plain_ask":
        answer, path = await _answer(model, text)
        return AskResponse(text=answer, path=path, tool_used=None, escalated=False)

    if intent.route == "build":
        return AskResponse(text=_BUILD_SIGNAL, path="build", tool_used=None, escalated=False)

    if intent.route == "aggregate":
        return AskResponse(
            text=_AGGREGATE_SIGNAL, path="aggregate", tool_used=None, escalated=False
        )

    tavily_api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not tavily_api_key:
        answer, _path = await _answer(model, text)
        return AskResponse(
            text=f"{_NO_SEARCH_PREFIX}{answer}",
            path="local",
            tool_used=None,
            escalated=False,
        )

    web_tool = build_web_tool(tavily_api_key=tavily_api_key)
    try:
        web_answer = await web_tool.answer(text)
    finally:
        await web_tool.aclose()
    return AskResponse(text=web_answer.answer, path="web", tool_used="web", escalated=False)


async def _invoke_or_routed_answer(
    *,
    selector: CapabilitySelector,
    capability_store: FileCapabilityStore,
    invokes: dict[str, InvokeState],
    model: ModelPort,
    intent_router: IntentRouter,
    text: str,
) -> AskResponse:
    selection = await selector.select(text)
    if selection.matched and selection.capability and not selection.missing_required:
        skill = capability_store.get(selection.capability)
        if skill is None:
            return await _routed_answer(model, intent_router, text)

        proposal = build_invoke_proposal(selection, skill, invokes, text)
        return AskResponse(
            text=f"Ready to run '{proposal.capability}'. Confirm to proceed.",
            path="invoke_confirm",
            invoke_id=proposal.invoke_id,
            capability=proposal.capability,
            egress_domains=proposal.egress_domains,
            secrets=proposal.secrets,
            args=proposal.args,
        )

    if selection.matched and selection.missing_required:
        return AskResponse(
            text=f"I need more detail to run '{selection.capability}': "
            + ", ".join(selection.missing_required),
            path="invoke_clarify",
            capability=selection.capability,
            missing=selection.missing_required,
        )

    return await _routed_answer(model, intent_router, text)


router = APIRouter(prefix="/app")


@router.post("/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    _principal: Principal = Depends(require_session),
    model: ModelPort = Depends(_router),
    intent_router: IntentRouter = Depends(_intent),
    selector: CapabilitySelector = Depends(_selector),
    capability_store: FileCapabilityStore = Depends(_capability_store),
    invokes: dict[str, InvokeState] = Depends(_invokes),
) -> AskResponse:
    return await _invoke_or_routed_answer(
        selector=selector,
        capability_store=capability_store,
        invokes=invokes,
        model=model,
        intent_router=intent_router,
        text=req.text,
    )


@router.post("/ask/stream")
async def ask_stream(
    req: AskRequest,
    _principal: Principal = Depends(require_session),
    model: ModelPort = Depends(_router),
    intent_router: IntentRouter = Depends(_intent),
    selector: CapabilitySelector = Depends(_selector),
    capability_store: FileCapabilityStore = Depends(_capability_store),
    invokes: dict[str, InvokeState] = Depends(_invokes),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        response = await _invoke_or_routed_answer(
            selector=selector,
            capability_store=capability_store,
            invokes=invokes,
            model=model,
            intent_router=intent_router,
            text=req.text,
        )
        yield _sse_event(response.text)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/ask/invoke/{invoke_id}/confirm", response_model=InvokeConfirmResponse)
async def confirm_invoke_route(
    invoke_id: str,
    request: Request,
    _principal: Principal = Depends(require_session),
    capability_store: FileCapabilityStore = Depends(_capability_store),
    secrets_store: SecretStorePort = Depends(_secrets),
    sandbox: FetchSandbox = Depends(_fetch_sandbox),
    synth: ModelPort = Depends(_router),
    reader: ModelPort = Depends(_quarantine_reader),
) -> InvokeConfirmResponse:
    invokes = _invokes(request)
    state = invokes.pop(invoke_id, None)
    if state is None:
        return InvokeConfirmResponse(invoke_id=invoke_id, status="not_found")

    result = await confirm_invoke(
        state,
        capability_store=capability_store,
        secrets_store=secrets_store,
        sandbox=sandbox,
        reader=reader,
        synth=synth,
    )
    if result.status == "missing_secrets":
        invokes[invoke_id] = state
    return InvokeConfirmResponse(
        invoke_id=invoke_id,
        status=result.status,
        text=result.text,
        missing_secrets=result.missing_secrets,
    )


@router.post("/ask/voice")
async def ask_voice(
    req: AskRequest,
    _principal: Principal = Depends(require_session),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        yield _sse_event("Voice answers aren't available yet.")
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
