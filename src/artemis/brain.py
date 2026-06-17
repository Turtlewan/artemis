"""Brain reactive loop — router-first, constrained-decoded dispatch, responder.

Thin custom orchestrator (brain.md): route → dispatch tool (constrained decoding)
→ responder → escalation stub. No heavyweight framework.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from artemis.ports.model import ModelPort
from artemis.ports.types import Message, Scope
from artemis.registry.registry import ToolRegistry
from artemis.router import SemanticRouter

logger = logging.getLogger(__name__)


class BrainResponse:
    """Structured response from the Brain."""

    def __init__(
        self,
        text: str,
        path: str,
        tool_used: str | None = None,
        escalated: bool = False,
    ) -> None:
        self.text = text
        self.path = path
        self.tool_used = tool_used
        self.escalated = escalated


class Brain:
    """Router-first reactive brain loop.

    For each request: route → dispatch tool (constrained decoding for args)
    → render answer → or use free-form responder → or stub escalation.
    All three paths are async (ADR-015).
    """

    def __init__(
        self,
        router: SemanticRouter,
        registry: ToolRegistry,
        model: ModelPort,
    ) -> None:
        self._router = router
        self._registry = registry
        self._model = model

    async def respond(self, request_text: str, scope: Scope) -> BrainResponse:
        """Process a single request through the brain loop.

        Returns a ``BrainResponse`` — never raises (degrade-don't-crash).
        """
        try:
            decision = await self._router.route(request_text, scope)
        except Exception:
            logger.warning("Brain: router failed, returning escalation stub", exc_info=True)
            return BrainResponse(text="ESCALATION_NOT_AVAILABLE", path="escalate", escalated=True)

        # ── Escalation stub ────────────────────────────────────────────
        if decision.path == "escalate":
            return BrainResponse(
                text="ESCALATION_NOT_AVAILABLE",
                path="escalate",
                escalated=True,
            )

        # ── Tool path ──────────────────────────────────────────────────
        if decision.candidate_tools:
            fq_id = decision.candidate_tools[0]
            try:
                spec = self._registry.get_tool(fq_id)
                # Constrained decode: ask the model to produce valid JSON args
                msg = Message(
                    role="user",
                    content=f"Call the tool '{spec.name}' with appropriate arguments for: {request_text}",
                )
                result = await self._model.complete(
                    role="responder",
                    messages=[msg],
                    response_schema=spec.args_json_schema(),
                )
                args_model = spec.args_schema.model_validate_json(result.text)
                tool_result = await spec.callable_ref(args_model)
                rendered = f"{tool_result.model_dump()}"
                return BrainResponse(
                    text=rendered,
                    path=decision.path,
                    tool_used=fq_id,
                )
            except Exception:
                logger.warning(
                    "Brain: tool dispatch failed for %s, returning TOOL_ERROR", fq_id, exc_info=True
                )
                return BrainResponse(text="TOOL_ERROR", path=decision.path, tool_used=fq_id)

        # ── Free-form responder path ───────────────────────────────────
        try:
            msg = Message(role="user", content=request_text)
            result = await self._model.complete(role="responder", messages=[msg])
            return BrainResponse(
                text=result.text,
                path="local",
            )
        except Exception:
            logger.warning("Brain: responder failed, returning escalation stub", exc_info=True)
            return BrainResponse(text="ESCALATION_NOT_AVAILABLE", path="escalate", escalated=True)

    async def respond_stream(self, request_text: str, scope: Scope) -> AsyncIterator[str]:
        """Stream a response — yields text segments.

        Tool path and escalation stub yield one segment; free-form
        responder yields the streamed tokens from ``ModelPort.complete_stream``.
        """
        decision = await self._router.route(request_text, scope)

        if decision.path == "escalate" or decision.candidate_tools:
            response = await self.respond(request_text, scope)
            yield response.text
            return

        # Stream from the free-form responder
        msg = Message(role="user", content=request_text)
        async for chunk in self._model.complete_stream(role="responder", messages=[msg]):
            yield chunk

    async def pre_route(self, request_text: str, scope: Scope) -> str | None:
        """Classify a request and return the top candidate tool id, if any.

        No model call — routing only. Used by the voice surface (M5-c)
        to classify Tier pre-serve and withhold sensitive data.
        """
        decision = await self._router.route(request_text, scope)
        if decision.candidate_tools:
            return decision.candidate_tools[0]
        return None
