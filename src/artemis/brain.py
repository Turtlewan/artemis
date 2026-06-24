"""Brain reactive loop — router-first, constrained-decoded dispatch, responder.

Thin custom orchestrator (brain.md): route → dispatch tool (constrained decoding)
→ responder → escalation stub. No heavyweight framework.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from artemis.identity.scope import OWNER_PRIVATE
from artemis.memory.store import render_inject_block
from artemis.memory.write_path import MemoryWriteQueue
from artemis.obs import NullSink, ObservabilitySink
from artemis.ports.memory import MemoryStore
from artemis.ports.model import ModelPort
from artemis.ports.types import Message, PersonId, Scope
from artemis.recipes.distill import apply_recipe, task_class_key
from artemis.recipes.model import RecipeStatus
from artemis.recipes.sandbox import SandboxPort
from artemis.recipes.store import RecipeStore
from artemis.registry.registry import ToolRegistry
from artemis.router import SemanticRouter

if TYPE_CHECKING:
    from artemis.recipes.promotion import Promoter
    from artemis.retrieval.agentic import AgenticRetriever
    from artemis.sensitivity import SensitivityClassifierProtocol

logger = logging.getLogger(__name__)


class TelemetryWriter(Protocol):
    """Minimal telemetry tap for escalation events."""

    def write_event(self, event: str, fields: dict[str, object]) -> None:
        """Write a telemetry event."""
        ...


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
        classifier: SensitivityClassifierProtocol | None = None,
        cloud_reasoning_enabled: bool = True,
        memory: MemoryStore | None = None,
        write_queue: MemoryWriteQueue | None = None,
        inject_token_budget: int = 512,
        owner_person_id: PersonId | None = None,
        store: RecipeStore | None = None,
        sandbox: SandboxPort | None = None,
        telemetry_writer: TelemetryWriter | None = None,
        promoter: Promoter | None = None,
        agentic: AgenticRetriever | None = None,
        obs: ObservabilitySink = NullSink(),
    ) -> None:
        self._router = router
        self._registry = registry
        self._model = model
        self._classifier = classifier
        self._cloud_enabled = cloud_reasoning_enabled
        self._memory = memory
        self._write_queue = write_queue
        self._inject_token_budget = inject_token_budget
        self._owner_person_id = owner_person_id
        self._store = store
        self._sandbox = sandbox
        self._telemetry_writer = telemetry_writer
        self._promoter = promoter
        self.agentic = agentic
        self._obs = obs

    async def _responder_role(self, request_text: str) -> str:
        """Pick the free-form responder role: local unless classified general."""
        classifier = self._classifier
        if not self._cloud_enabled or classifier is None:
            return "responder"
        try:
            sensitivity = await classifier.classify(request_text)
        except Exception:
            logger.warning("Brain: sensitivity classifier raised -- failing closed to local")
            return "responder"
        return "responder" if sensitivity == "sensitive" else "responder_cloud"

    async def respond(self, request_text: str, scope: Scope) -> BrainResponse:
        """Process a single request through the brain loop.

        Returns a ``BrainResponse`` — never raises (degrade-don't-crash).
        """
        try:
            decision = await self._router.route(request_text, scope)
        except Exception:
            logger.warning("Brain: router failed, returning escalation stub", exc_info=True)
            return BrainResponse(text="ESCALATION_NOT_AVAILABLE", path="escalate", escalated=True)
        key = task_class_key(decision, request_text)
        self._obs.on_route_decision(
            key,
            decision.confidence,
            decision.path,
            now=datetime.now(UTC),
        )

        # ── Escalation stub ────────────────────────────────────────────
        # Schedule M4-b extraction once after a successful route; enqueue is non-blocking.
        if (
            self._write_queue is not None
            and self._owner_person_id is not None
            and scope == OWNER_PRIVATE
        ):
            try:
                self._write_queue.enqueue(request_text, turn_id=uuid.uuid4().hex, role="user")
            except Exception:
                logger.warning("Brain: memory write enqueue failed", exc_info=True)

        if decision.path == "escalate":
            if self.agentic is not None:
                try:
                    agentic_result = await self.agentic.run(request_text, scope)
                    if agentic_result.chunks:
                        return BrainResponse(
                            text=agentic_result.answer,
                            path="agentic",
                            escalated=False,
                        )
                except Exception:
                    logger.warning("Brain: agentic retrieval failed", exc_info=True)
                    return BrainResponse(
                        text="RETRIEVAL_ERROR",
                        path="agentic",
                        escalated=False,
                    )
            if self._store is None:
                return BrainResponse(
                    text="ESCALATION_NOT_AVAILABLE",
                    path="escalate",
                    escalated=True,
                )
            try:
                names = await self._store.retrieve_recipes(
                    request_text,
                    k=1,
                    status=RecipeStatus.ENABLED,
                )
                if names:
                    recipe = self._store.get(names[0])
                    if recipe.task_class_key == key:
                        applied = await apply_recipe(
                            recipe,
                            {
                                "request_text": request_text,
                                "scope": scope,
                                "task_class_key": key,
                            },
                            self._model,
                            sandbox=self._sandbox,
                        )
                        return BrainResponse(
                            text=json.dumps(applied, sort_keys=True),
                            path="recipe",
                            tool_used=names[0],
                            escalated=False,
                        )
            except Exception:
                logger.warning("Brain: recipe apply failed, queueing escalation", exc_info=True)

            telemetry_writer = self._telemetry_writer
            if telemetry_writer is not None:
                try:
                    telemetry_writer.write_event(
                        "ESCALATION",
                        {
                            "task_class_key": key,
                            "scope": scope,
                            "request_text": request_text,
                        },
                    )
                except Exception:
                    logger.warning("Brain: escalation telemetry write failed", exc_info=True)
            if (
                self._promoter is not None
                and self._store is not None
                and any(
                    recipe.task_class_key == key
                    for recipe in self._store.list(status=RecipeStatus.CANDIDATE)
                )
            ):
                await self._promoter.note_occurrence(key)
            return BrainResponse(text="", path="escalation_queued", escalated=True)

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
            except Exception as exc:
                logger.warning(
                    "Brain: tool dispatch failed for %s, returning TOOL_ERROR", fq_id, exc_info=True
                )
                self._obs.on_error("brain", exc, now=datetime.now(UTC))
                return BrainResponse(text="TOOL_ERROR", path=decision.path, tool_used=fq_id)

        # ── Free-form responder path ───────────────────────────────────
        try:
            role = await self._responder_role(request_text)
            messages = [Message(role="user", content=request_text)]
            # SECURITY: inject owner facts ONLY into the LOCAL responder, never the cloud one.
            if (
                self._memory is not None
                and self._owner_person_id is not None
                and scope == OWNER_PRIVATE
                and role == "responder"
            ):
                try:
                    facts = await self._memory.inject_context(
                        self._owner_person_id, self._inject_token_budget
                    )
                    block = render_inject_block(facts)
                    if block:
                        messages = [
                            Message(role="system", content=block),
                            Message(role="user", content=request_text),
                        ]
                except Exception:
                    logger.warning(
                        "Brain: memory inject failed -- proceeding without memory block",
                        exc_info=True,
                    )
            result = await self._model.complete(role=role, messages=messages)
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
        role = await self._responder_role(request_text)
        try:
            async for chunk in self._model.complete_stream(role=role, messages=[msg]):
                yield chunk
        except Exception as exc:
            logger.warning(
                "Brain: responder stream failed, returning escalation stub", exc_info=True
            )
            self._obs.on_error("brain", exc, now=datetime.now(UTC))
            yield "ESCALATION_NOT_AVAILABLE"

    async def pre_route(self, request_text: str, scope: Scope) -> str | None:
        """Classify a request and return the top candidate tool id, if any.

        No model call — routing only. Used by the voice surface (M5-c)
        to classify Tier pre-serve and withhold sensitive data.
        """
        decision = await self._router.route(request_text, scope)
        if decision.candidate_tools:
            return decision.candidate_tools[0]
        return None
