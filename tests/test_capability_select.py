from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from artemis.capabilities.select import (
    CONFIDENCE_THRESHOLD,
    CapabilitySelector,
    SelectionResult,
    build_capability_selector,
)
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.model.router import QuotaAwareRouter
from artemis.ports.capabilities import CapabilityStore
from artemis.ports.model import ModelPort
from artemis.types import (
    Message,
    ModelResponse,
    Skill,
    SkillDraft,
    SkillInputParam,
    StagedSkill,
    Usage,
)


class FakeModel:
    def __init__(self, response: str | None = None, *, raises: Exception | None = None) -> None:
        self.response = response or _pick("Planner", {"topic": "work"}, 0.9)
        self.raises = raises
        self.calls: list[Sequence[Message]] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del response_schema
        assert model == "haiku"
        assert temperature == 0.0
        assert max_tokens == 400
        self.calls.append(messages)
        if self.raises is not None:
            raise self.raises
        return ModelResponse(
            text=self.response,
            model_id=model or "haiku",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FakeCapabilityStore:
    def __init__(self, skills: list[Skill]) -> None:
        self.skills = skills
        self.retrieve_calls: list[tuple[str, int]] = []

    async def stage(self, draft: SkillDraft) -> StagedSkill:
        raise NotImplementedError

    async def promote(self, staged_id: str) -> Skill:
        raise NotImplementedError

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        tags: Sequence[str] | None = None,
    ) -> list[Skill]:
        del tags
        self.retrieve_calls.append((query, k))
        return self.skills[:k]

    def get(self, name: str) -> Skill | None:
        return next((skill for skill in self.skills if skill.name == name), None)


def test_selector_models_import_and_constant() -> None:
    assert CONFIDENCE_THRESHOLD == 0.5
    assert SelectionResult(
        matched=False,
        capability=None,
        args={},
        confidence=0.0,
        missing_required=[],
    )


@pytest.mark.asyncio
async def test_match_with_full_args() -> None:
    skill = _skill(
        "Planner",
        [
            SkillInputParam(name="topic", type="string", description="Topic"),
            SkillInputParam(name="count", type="number", description="Count"),
        ],
    )
    selector = CapabilitySelector(
        store=FakeCapabilityStore([skill]),
        model=FakeModel(_pick("Planner", {"topic": "work", "count": 2}, 0.9)),
    )

    result = await selector.select("plan two work items")

    assert result.matched is True
    assert result.capability == "Planner"
    assert result.args == {"topic": "work", "count": 2}
    assert result.missing_required == []


@pytest.mark.asyncio
async def test_match_with_missing_required_arg() -> None:
    skill = _skill(
        "Planner",
        [
            SkillInputParam(name="topic", type="string", description="Topic"),
            SkillInputParam(name="count", type="number", description="Count"),
        ],
    )
    selector = CapabilitySelector(
        store=FakeCapabilityStore([skill]),
        model=FakeModel(_pick("Planner", {"topic": "work"}, 0.9)),
    )

    result = await selector.select("plan work")

    assert result.matched is True
    assert result.capability == "Planner"
    assert result.args == {"topic": "work"}
    assert result.missing_required == ["count"]


@pytest.mark.asyncio
async def test_type_coercion_and_required_uncoercible_missing() -> None:
    skill = _skill(
        "Counter",
        [
            SkillInputParam(name="count", type="number", description="Count"),
            SkillInputParam(name="enabled", type="boolean", description="Enabled"),
            SkillInputParam(name="bad", type="number", description="Bad"),
        ],
    )
    selector = CapabilitySelector(
        store=FakeCapabilityStore([skill]),
        model=FakeModel(
            _pick(
                "Counter",
                {"count": "42", "enabled": "yes", "bad": "not-number", "extra": "drop"},
                0.9,
            )
        ),
    )

    result = await selector.select("count things")

    assert result.matched is True
    assert result.args == {"count": 42, "enabled": True}
    assert isinstance(result.args["count"], int)
    assert result.missing_required == ["bad"]


@pytest.mark.asyncio
async def test_no_candidates_returns_no_match_without_model_call() -> None:
    model = FakeModel()
    selector = CapabilitySelector(store=FakeCapabilityStore([]), model=model)

    result = await selector.select("anything")

    assert result == SelectionResult(
        matched=False,
        capability=None,
        args={},
        confidence=0.0,
        missing_required=[],
    )
    assert model.calls == []


@pytest.mark.asyncio
async def test_low_confidence_returns_no_match() -> None:
    selector = CapabilitySelector(
        store=FakeCapabilityStore([_skill("Planner")]),
        model=FakeModel(_pick("Planner", {}, 0.3)),
    )

    result = await selector.select("plan")

    assert result.matched is False


@pytest.mark.asyncio
async def test_null_capability_returns_no_match() -> None:
    selector = CapabilitySelector(
        store=FakeCapabilityStore([_skill("Planner")]),
        model=FakeModel(_pick(None, {}, 0.9)),
    )

    result = await selector.select("plan")

    assert result.matched is False


@pytest.mark.asyncio
async def test_hallucinated_capability_returns_no_match() -> None:
    selector = CapabilitySelector(
        store=FakeCapabilityStore([_skill("Planner")]),
        model=FakeModel(_pick("Unknown", {}, 0.9)),
    )

    result = await selector.select("plan")

    assert result.matched is False


@pytest.mark.asyncio
async def test_model_error_degrades_safely() -> None:
    selector = CapabilitySelector(
        store=FakeCapabilityStore([_skill("Planner")]),
        model=FakeModel(raises=RuntimeError("boom")),
    )

    result = await selector.select("plan")

    assert result.matched is False


@pytest.mark.asyncio
async def test_malformed_model_output_degrades_safely() -> None:
    selector = CapabilitySelector(
        store=FakeCapabilityStore([_skill("Planner")]),
        model=FakeModel('{"capability": "Planner", "args": {}, "confidence": 2.0}'),
    )

    result = await selector.select("plan")

    assert result.matched is False


def test_build_capability_selector_uses_dedicated_haiku_port_not_router() -> None:
    selector = build_capability_selector(FakeCapabilityStore([]))

    assert isinstance(selector._model, ModelClient)
    assert isinstance(selector._model._provider, ClaudeCodeProvider)
    assert selector._model._model_default == "haiku"
    assert not isinstance(selector._model, QuotaAwareRouter)


def test_fakes_satisfy_ports() -> None:
    assert isinstance(FakeModel(), ModelPort)
    assert isinstance(FakeCapabilityStore([]), CapabilityStore)


def _pick(capability: str | None, args: dict[str, object], confidence: float) -> str:
    return json.dumps({"capability": capability, "args": args, "confidence": confidence})


def _skill(name: str, inputs: list[SkillInputParam] | None = None) -> Skill:
    return Skill(
        name=name,
        description=f"{name} description",
        version=1,
        path=f"/fake/{name}",
        tags=[],
        uses=[],
        secrets=[],
        inputs=inputs or [],
        egress_domains=[],
    )
