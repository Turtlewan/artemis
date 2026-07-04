"""Match-first capability selection for owner requests."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.ports.capabilities import CapabilityStore
from artemis.ports.model import ModelPort
from artemis.types import Message, Skill, SkillInputParam

_log = logging.getLogger(__name__)

# Tunable gate for accepting a model-picked capability.
CONFIDENCE_THRESHOLD: float = 0.5


class SelectionResult(BaseModel):
    """Serializable result of selecting a capability without running it."""

    model_config = ConfigDict(frozen=True)

    matched: bool
    capability: str | None
    args: dict[str, object]
    confidence: float
    missing_required: list[str]


class _SelectionPick(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability: str | None
    args: dict[str, object]
    confidence: float = Field(ge=0.0, le=1.0)


_PICK_SCHEMA = cast(dict[str, object], _SelectionPick.model_json_schema())

_SYSTEM = (
    "You select at most one Artemis capability for the owner's request. "
    "Return only JSON matching the schema. Use capability=null when none fits. "
    "Only choose a capability name from the provided candidates. Extract args using the "
    "candidate input names and primitive input types."
)


class CapabilitySelector:
    """Select a shortlisted capability using a dedicated Haiku model port."""

    def __init__(
        self,
        *,
        store: CapabilityStore,
        model: ModelPort,
        model_override: str | None = "haiku",
        k: int = 5,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
    ) -> None:
        self._store = store
        self._model = model
        self._model_override = model_override
        self._k = k
        self._confidence_threshold = confidence_threshold

    async def select(self, request: str) -> SelectionResult:
        """Return a validated selection, degrading to no-match on model or parse failures."""

        candidates = await self._store.retrieve(request, k=self._k)
        if not candidates:
            return _no_match()

        try:
            response = await self._model.complete(
                messages=[
                    Message(role="system", content=_SYSTEM),
                    Message(role="user", content=_build_user_prompt(request, candidates)),
                ],
                model=self._model_override,
                response_schema=_PICK_SCHEMA,
                temperature=0.0,
                max_tokens=400,
            )
            pick = _SelectionPick.model_validate_json(response.text)
        except Exception as exc:
            _log.warning("capability_select_degraded reason=%s", type(exc).__name__)
            return _no_match()

        matched = {skill.name: skill for skill in candidates}.get(pick.capability or "")
        if (
            pick.capability is None
            or pick.confidence < self._confidence_threshold
            or matched is None
        ):
            return _no_match()

        args, missing_required = _coerce_args(matched.inputs, pick.args)
        return SelectionResult(
            matched=True,
            capability=pick.capability,
            args=args,
            confidence=pick.confidence,
            missing_required=missing_required,
        )


def build_capability_selector(
    store: CapabilityStore, *, model: ModelPort | None = None
) -> CapabilitySelector:
    """Build the selector over an injected role-resolved port when provided."""

    if model is not None:
        return CapabilitySelector(store=store, model=model, model_override=None)

    return CapabilitySelector(
        store=store,
        model=ModelClient(ClaudeCodeProvider(), model_default="haiku"),
    )


def _no_match() -> SelectionResult:
    return SelectionResult(
        matched=False,
        capability=None,
        args={},
        confidence=0.0,
        missing_required=[],
    )


def _build_user_prompt(request: str, candidates: Sequence[Skill]) -> str:
    rendered = "\n".join(_render_candidate(skill) for skill in candidates)
    return f"Owner request:\n{request}\n\nCandidate capabilities:\n{rendered}"


def _render_candidate(skill: Skill) -> str:
    inputs = ", ".join(
        (
            f"{param.name} type={param.type} required={param.required} "
            f"description={param.description}"
        )
        for param in skill.inputs
    )
    rendered_inputs = inputs or "none"
    return f"- name={skill.name}\n  description={skill.description}\n  inputs={rendered_inputs}"


def _coerce_args(
    inputs: list[SkillInputParam],
    raw: dict[str, object],
) -> tuple[dict[str, object], list[str]]:
    coerced: dict[str, object] = {}
    missing_required: list[str] = []
    for param in inputs:
        value = raw.get(param.name)
        if value is None:
            if param.required:
                missing_required.append(param.name)
            continue

        coerced_value = _coerce_value(param.type, value)
        if coerced_value is None:
            if param.required:
                missing_required.append(param.name)
            continue

        coerced[param.name] = coerced_value
    return coerced, missing_required


def _coerce_value(param_type: str, value: object) -> object | None:
    if param_type == "string":
        return str(value)
    if param_type == "number":
        return _coerce_number(value)
    if param_type == "boolean":
        return _coerce_bool(value)
    return None


def _coerce_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            if "." in stripped or "e" in stripped.lower():
                return float(stripped)
            return int(stripped)
        except ValueError:
            return None
    return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        table = {
            "true": True,
            "t": True,
            "yes": True,
            "y": True,
            "1": True,
            "false": False,
            "f": False,
            "no": False,
            "n": False,
            "0": False,
        }
        return table.get(value.strip().lower())
    return None
