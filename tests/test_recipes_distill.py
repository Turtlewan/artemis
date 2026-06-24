from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import cast

import pytest

from artemis.brain import Brain
from artemis.ports.model import ModelResponse
from artemis.ports.routing import RouteDecision
from artemis.ports.types import Message, Scope, Vector
from artemis.recipes import (
    RECIPE_SCHEMA,
    ActionClass,
    CloudEgressForbiddenError,
    DistillService,
    EscalationRequest,
    Recipe,
    RecipeClass,
    RecipeReplayError,
    RecipeSigner,
    RecipeStatus,
    RecipeStore,
    SandboxNotAvailableError,
    TeacherOutcome,
    apply_recipe,
    task_class_key,
)
from artemis.recipes.sandbox import FakeSandbox
from artemis.registry import ToolRegistry
from artemis.router import SemanticRouter


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 8

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._embed(query)

    def _embed(self, text: str) -> Vector:
        tokens = {token.strip(".,").lower() for token in text.split()}
        values = [0.0] * self.dimension
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            values[digest[0] % self.dimension] += 1.0
        return values


class FakeKeyProvider:
    def signing_key(self) -> bytes:
        return b"test-recipe-distill-signing-key"


class FakeTeacher:
    def __init__(self, *, responder_payload: dict[str, object] | None = None) -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self.distill_prompts: list[str] = []
        self.responder_payload = responder_payload or {"summary": "schema-valid replay"}

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del temperature, max_tokens
        prompt = messages[-1].content
        self.calls.append((role, prompt, response_schema is not None))
        if role == "teacher" and response_schema == RECIPE_SCHEMA:
            self.distill_prompts.append(prompt)
            return ModelResponse(text=json.dumps(_recipe_payload()))
        if role == "teacher":
            return ModelResponse(text="teacher solved the instance")
        if role == "responder":
            return ModelResponse(text=json.dumps(self.responder_payload))
        return ModelResponse(text="{}")

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature

        async def _gen() -> AsyncIterator[str]:
            yield "chunk"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


class SpyModelPort(FakeTeacher):
    pass


class FakeRouter:
    def __init__(self, decision: RouteDecision) -> None:
        self._decision = decision

    async def route(self, request_text: str, scope: Scope) -> RouteDecision:
        del request_text, scope
        return self._decision


class SpyTelemetryWriter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def write_event(self, event: str, fields: dict[str, object]) -> None:
        self.events.append((event, fields))


def _recipe_payload() -> dict[str, object]:
    return {
        "name": "summarize_request",
        "description": "summarize request for replay verification",
        "recipe_class": "instructions",
        "action_class": "read-only",
        "inputs_schema": {"type": "object"},
        "outputs_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        "instructions": "Summarize the request into a short summary.",
        "script": None,
    }


def _store(tmp_path: Path) -> RecipeStore:
    return RecipeStore(FakeEmbedder(), tmp_path, signer=RecipeSigner(FakeKeyProvider()))


def _request() -> EscalationRequest:
    return EscalationRequest(
        request_text="Summarize my private agenda item",
        scope="owner-private",
        task_class_key="summary.task",
        is_cloud_safe=True,
    )


def _enabled_recipe() -> Recipe:
    return Recipe(
        name="summarize_request",
        description="summarize request replay verification",
        version="0.1.0",
        recipe_class=RecipeClass.INSTRUCTIONS,
        action_class=ActionClass.READ_ONLY,
        task_class_key="summary.task",
        inputs_schema={"type": "object"},
        outputs_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        instructions="Summarize the request into a short summary.",
        status=RecipeStatus.ENABLED,
        provenance={"source": "test"},
    )


def _script_recipe() -> Recipe:
    return Recipe(
        name="script_recipe",
        description="script recipe",
        version="0.1.0",
        recipe_class=RecipeClass.SCRIPT,
        action_class=ActionClass.READ_ONLY,
        task_class_key="script.task",
        inputs_schema={"type": "object"},
        outputs_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
        instructions="Run the script.",
        script="result = {'summary': request_text}",
        status=RecipeStatus.CANDIDATE,
        provenance={"source": "test"},
    )


def test_task_class_key_uses_candidate_or_normalized_hash() -> None:
    decision = RouteDecision(path="escalate", candidate_tools=["calendar.focus"], confidence=0.1)
    assert task_class_key(decision, "anything") == "calendar.focus"

    empty = RouteDecision(path="escalate", candidate_tools=[], confidence=0.0)
    assert task_class_key(empty, "  Hello   WORLD ") == task_class_key(empty, "hello world")


async def test_escalate_distill_candidate_is_signed_verified_and_instance_free(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    teacher = FakeTeacher()
    req = _request()
    service = DistillService(model=teacher, store=store, teacher_origin="local")

    recipe = await service.escalate_and_distill(req)

    loaded = store.get(recipe.name)
    assert loaded.status == RecipeStatus.CANDIDATE
    assert loaded.signature is not None
    assert loaded.provenance["verified_at"]
    assert teacher.distill_prompts
    assert req.request_text not in teacher.distill_prompts[-1]


async def test_cloud_egress_refusal_happens_before_model_call(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spy = SpyModelPort()
    req = EscalationRequest(
        request_text="sensitive details",
        scope="owner-private",
        task_class_key="sensitive.task",
        is_cloud_safe=False,
    )
    service = DistillService(model=spy, store=store, teacher_origin="cloud")

    with pytest.raises(CloudEgressForbiddenError):
        await service.escalate_and_distill(req)

    assert spy.calls == []


async def test_replay_verify_failure_writes_no_candidate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    teacher = FakeTeacher(responder_payload={"summary": 123})
    service = DistillService(model=teacher, store=store, teacher_origin="local")

    with pytest.raises(RecipeReplayError):
        await service.escalate_and_distill(_request())

    assert store.list() == []


async def test_script_recipe_without_sandbox_refuses_apply_and_replay(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = DistillService(model=FakeTeacher(), store=store, teacher_origin="local")
    recipe = _script_recipe()
    req = _request()

    with pytest.raises(SandboxNotAvailableError):
        await apply_recipe(recipe, {"request_text": "x"}, FakeTeacher(), sandbox=None)
    with pytest.raises(SandboxNotAvailableError):
        await service.replay_verify(
            recipe,
            req,
            expected=TeacherOutcome(text="teacher", outcome_hash="hash"),
        )

    ready_service = DistillService(
        model=FakeTeacher(),
        store=store,
        teacher_origin="local",
        sandbox=FakeSandbox({"summary": "ok"}, ready=True),
    )
    assert await ready_service.replay_verify(
        recipe,
        req,
        expected=TeacherOutcome(text="teacher", outcome_hash="hash"),
    )


async def test_brain_applies_enabled_recipe_without_teacher_call(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.write(_enabled_recipe())
    model = FakeTeacher()
    brain = Brain(
        cast(
            SemanticRouter,
            FakeRouter(
                RouteDecision(path="escalate", candidate_tools=["summary.task"], confidence=0.1)
            ),
        ),
        ToolRegistry(FakeEmbedder()),
        model,
        store=store,
    )

    response = await brain.respond("summarize request replay", "owner-private")

    assert response.path == "recipe"
    assert response.tool_used == "summarize_request"
    assert json.loads(response.text) == {"summary": "schema-valid replay"}
    assert [call for call in model.calls if call[0] == "teacher"] == []


async def test_brain_queues_escalation_and_emits_telemetry_with_no_recipe(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    telemetry = SpyTelemetryWriter()
    model = FakeTeacher()
    brain = Brain(
        cast(
            SemanticRouter,
            FakeRouter(RouteDecision(path="escalate", candidate_tools=[], confidence=0.0)),
        ),
        ToolRegistry(FakeEmbedder()),
        model,
        store=store,
        telemetry_writer=telemetry,
    )

    response = await brain.respond("unmatched escalation", "owner-private")

    assert response.path == "escalation_queued"
    assert response.text == ""
    assert response.escalated is True
    assert len(telemetry.events) == 1
    assert telemetry.events[0][0] == "ESCALATION"
    assert [call for call in model.calls if call[0] == "teacher"] == []
