"""Teacher distillation, replay verification, and recipe application.

The lifecycle is escalate to a teacher, distill the task-class method into a
candidate recipe, replay the candidate against the original teacher outcome,
then persist only verified candidates. Runtime apply is automation, not a
teacher call: script recipes require a ready sandbox, and instruction recipes
use one responder call.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from artemis.ports.model import ModelPort, ModelResponse
from artemis.ports.routing import RouteDecision
from artemis.ports.types import Message, Scope
from artemis.recipes.model import (
    RECIPE_SCHEMA,
    ActionClass,
    Recipe,
    RecipeClass,
    RecipeStatus,
)
from artemis.recipes.sandbox import SandboxNotAvailableError, SandboxPort
from artemis.recipes.store import RecipeStore


@dataclass(frozen=True)
class EscalationRequest:
    """Escalation inputs used for teacher solve and replay verification."""

    request_text: str
    scope: Scope
    task_class_key: str
    is_cloud_safe: bool


@dataclass(frozen=True)
class TeacherOutcome:
    """Teacher answer captured for candidate replay verification."""

    text: str
    outcome_hash: str


class CloudEgressForbiddenError(Exception):
    """Raised before a cloud teacher can see sensitive request data."""


class RecipeReplayError(Exception):
    """Raised when a distilled candidate fails replay verification."""


def now_iso() -> str:
    """Return the local ISO timestamp for replay provenance."""
    return datetime.now().isoformat()


def task_class_key(decision: RouteDecision, request_text: str) -> str:
    """Return the router candidate key, or a stable normalized request hash."""
    if decision.candidate_tools:
        return decision.candidate_tools[0]
    normalized = " ".join(request_text.lower().strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class DistillService:
    """Service for teacher solve, task-class distillation, and replay verify."""

    model: ModelPort
    store: RecipeStore
    teacher_origin: Literal["local", "cloud"]
    sandbox: SandboxPort | None = None

    async def escalate_and_distill(self, req: EscalationRequest) -> Recipe:
        """Escalate once, distill an instance-free recipe, verify, and persist."""
        if req.is_cloud_safe is False and self.teacher_origin == "cloud":
            raise CloudEgressForbiddenError("sensitive escalation cannot use cloud teacher")

        solution = await self.model.complete(
            role="teacher",
            messages=[Message(role="user", content=_solve_prompt(req.request_text))],
            max_tokens=1024,
        )
        outcome = TeacherOutcome(
            text=solution.text,
            outcome_hash=hashlib.sha256(solution.text.encode("utf-8")).hexdigest(),
        )

        distilled = await self.model.complete(
            role="teacher",
            messages=[
                Message(
                    role="user",
                    content=_distill_prompt(req.task_class_key, ActionClass.READ_ONLY),
                )
            ],
            response_schema=RECIPE_SCHEMA,
            max_tokens=2048,
        )
        recipe = _recipe_from_response(distilled, req, outcome)

        try:
            verified = await self.replay_verify(recipe, req, outcome)
        except SandboxNotAvailableError:
            raise
        except Exception as exc:
            raise RecipeReplayError("candidate replay verification failed") from exc
        if not verified:
            raise RecipeReplayError("candidate replay verification failed")

        await self.store.write(recipe)
        return recipe

    async def replay_verify(
        self,
        recipe: Recipe,
        req: EscalationRequest,
        expected: TeacherOutcome,
    ) -> bool:
        """Replay a candidate recipe and accept schema-conformant outputs."""
        del expected
        output = await apply_recipe(
            recipe,
            _inputs_from_request(req),
            self.model,
            sandbox=self.sandbox,
        )
        if not _conforms_to_schema(output, recipe.outputs_schema):
            return False
        recipe.provenance["verified_at"] = now_iso()
        return True


async def apply_recipe(
    recipe: Recipe,
    inputs: Mapping[str, object],
    model: ModelPort,
    *,
    sandbox: SandboxPort | None = None,
) -> dict[str, object]:
    """Apply a recipe without calling the teacher role."""
    if recipe.recipe_class == RecipeClass.SCRIPT:
        if sandbox is None or not sandbox.ready():
            raise SandboxNotAvailableError("script recipe requires a ready sandbox")
        if recipe.script is None:
            raise ValueError("script recipe has no script")
        output = sandbox.run(recipe.script, inputs, outputs_schema=recipe.outputs_schema)
        if not _conforms_to_schema(output, recipe.outputs_schema):
            raise RecipeReplayError("script output does not conform to schema")
        return output

    response = await model.complete(
        role="responder",
        messages=[Message(role="user", content=_apply_prompt(recipe, inputs))],
        response_schema=recipe.outputs_schema,
        max_tokens=1024,
    )
    output = _json_object(response.text)
    if not _conforms_to_schema(output, recipe.outputs_schema):
        raise RecipeReplayError("instruction output does not conform to schema")
    return output


async def escalate_and_distill(service: DistillService, req: EscalationRequest) -> Recipe:
    """Compatibility wrapper for package-level imports."""
    return await service.escalate_and_distill(req)


async def replay_verify(
    service: DistillService,
    recipe: Recipe,
    req: EscalationRequest,
    expected: TeacherOutcome,
) -> bool:
    """Compatibility wrapper for package-level imports."""
    return await service.replay_verify(recipe, req, expected)


def _solve_prompt(request_text: str) -> str:
    return f"Solve this user request. Return the useful answer only.\n\nRequest:\n{request_text}"


def _distill_prompt(task_key: str, action_class: ActionClass) -> str:
    return (
        "Distill a reusable Artemis recipe for a task class.\n"
        f"Task class key: {task_key}\n"
        f"Action class: {action_class.value}\n"
        "Do not include any instance data. Return JSON matching the provided recipe schema."
    )


def _apply_prompt(recipe: Recipe, inputs: Mapping[str, object]) -> str:
    return (
        "Apply this Artemis recipe using the structured inputs. "
        "Return only JSON matching the output schema.\n\n"
        f"Instructions:\n{recipe.instructions}\n\n"
        f"Inputs:\n{json.dumps(dict(inputs), sort_keys=True)}"
    )


def _inputs_from_request(req: EscalationRequest) -> dict[str, object]:
    return {
        "request_text": req.request_text,
        "scope": req.scope,
        "task_class_key": req.task_class_key,
    }


def _recipe_from_response(
    response: ModelResponse,
    req: EscalationRequest,
    outcome: TeacherOutcome,
) -> Recipe:
    payload = _json_object(response.text)
    recipe = Recipe(
        name=str(payload["name"]),
        description=str(payload["description"]),
        version="0.1.0",
        recipe_class=RecipeClass(str(payload["recipe_class"])),
        action_class=ActionClass(str(payload["action_class"])),
        task_class_key=req.task_class_key,
        inputs_schema=_object_dict(payload["inputs_schema"]),
        outputs_schema=_object_dict(payload["outputs_schema"]),
        instructions=str(payload["instructions"]),
        script=cast(str | None, payload.get("script")),
        status=RecipeStatus.CANDIDATE,
        provenance={
            "source": "teacher",
            "teacher_outcome_hash": outcome.outcome_hash,
            "verified_at": "",
        },
    )
    if not _conforms_to_schema(payload, RECIPE_SCHEMA):
        raise RecipeReplayError("distilled recipe does not conform to schema")
    return recipe


def _json_object(text: str) -> dict[str, object]:
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("model response must be a JSON object")
    return cast(dict[str, object], loaded)


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return cast(dict[str, object], value)


def _conforms_to_schema(value: object, schema: Mapping[str, object]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return False
        value_dict = cast(dict[str, object], value)
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value_dict:
                    return False
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, property_schema in properties.items():
                if not isinstance(key, str) or key not in value_dict:
                    continue
                if isinstance(property_schema, dict) and not _conforms_to_schema(
                    value_dict[key], cast(dict[str, object], property_schema)
                ):
                    return False
        additional = schema.get("additionalProperties")
        if additional is False and isinstance(properties, dict):
            allowed = {key for key in properties if isinstance(key, str)}
            if any(key not in allowed for key in value_dict):
                return False
        return True
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return (isinstance(value, int | float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "array":
        if not isinstance(value, list):
            return False
        items = schema.get("items")
        if isinstance(items, dict):
            return all(_conforms_to_schema(item, cast(dict[str, object], items)) for item in value)
        return True
    enum = schema.get("enum")
    if isinstance(enum, list):
        return value in enum
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and isinstance(value, str):
        return re.fullmatch(pattern, value) is not None
    return True
