"""Recipe data model and SKILL.md-shaped serialisation.

Recipes are runtime data: a YAML frontmatter block carries metadata and the
markdown body carries model-neutral instructions, with an optional fenced script
payload. The format is intentionally lossless so signed recipes can be loaded,
round-tripped, and verified deterministically.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Self, cast

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecipeClass(StrEnum):
    """Recipe implementation shape."""

    INSTRUCTIONS = "instructions"
    SCRIPT = "script"


class ActionClass(StrEnum):
    """Safety class consumed by later auto-enable and gating policy."""

    READ_ONLY = "read-only"
    NO_DATA = "no-data"
    TOUCHES_DATA = "touches-data"
    TAKES_ACTION = "takes-action"


class RecipeStatus(StrEnum):
    """Recipe lifecycle state."""

    CANDIDATE = "candidate"
    PENDING = "pending"
    ENABLED = "enabled"
    RETIRED = "retired"


class Recipe(BaseModel):
    """Atomic capability recipe persisted as frontmatter plus instructions."""

    model_config = ConfigDict(arbitrary_types_allowed=False)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    version: str
    recipe_class: RecipeClass
    action_class: ActionClass
    task_class_key: str
    inputs_schema: dict[str, object]
    outputs_schema: dict[str, object]
    instructions: str
    script: str | None = None
    status: RecipeStatus = RecipeStatus.CANDIDATE
    signature: str | None = None
    provenance: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _description_must_not_be_empty(self) -> Self:
        if not self.description.strip():
            raise ValueError("description must not be empty")
        return self

    def to_skill_md(self) -> str:
        """Serialise this recipe to a SKILL.md-shaped file."""
        frontmatter: dict[str, object] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "recipe_class": self.recipe_class.value,
            "action_class": self.action_class.value,
            "task_class_key": self.task_class_key,
            "inputs": self.inputs_schema,
            "outputs": self.outputs_schema,
            "script": self.script,
            "status": self.status.value,
            "signature": self.signature,
            "provenance": self.provenance,
        }
        yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False)
        body = self.instructions
        if self.script is not None:
            body = f"{body}\n\n```script\n{self.script}\n```"
        return f"---\n{yaml_text}---\n{body}"

    @classmethod
    def from_skill_md(cls, text: str) -> Recipe:
        """Parse a SKILL.md-shaped recipe."""
        if not text.startswith("---\n"):
            raise ValueError("recipe text must start with YAML frontmatter")
        try:
            raw_frontmatter, raw_body = text[4:].split("\n---\n", 1)
        except ValueError as exc:
            raise ValueError("recipe text must contain a closing frontmatter marker") from exc

        loaded = yaml.safe_load(raw_frontmatter)
        if not isinstance(loaded, dict):
            raise ValueError("recipe frontmatter must be a mapping")
        frontmatter = cast(dict[str, object], loaded)

        body = raw_body
        script = frontmatter.get("script")
        if script is not None and not isinstance(script, str):
            raise ValueError("script must be a string or null")
        if script is not None:
            suffix = f"\n\n```script\n{script}\n```"
            if body.endswith(suffix):
                body = body[: -len(suffix)]

        return cls(
            name=frontmatter["name"],
            description=frontmatter["description"],
            version=frontmatter["version"],
            recipe_class=frontmatter["recipe_class"],
            action_class=frontmatter["action_class"],
            task_class_key=frontmatter["task_class_key"],
            inputs_schema=frontmatter["inputs"],
            outputs_schema=frontmatter["outputs"],
            instructions=body,
            script=script,
            status=frontmatter.get("status", RecipeStatus.CANDIDATE),
            signature=frontmatter.get("signature"),
            provenance=frontmatter.get("provenance", {}),
        )


def _inline_refs(value: object, defs: dict[str, object]) -> object:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            key = ref.removeprefix("#/$defs/")
            return _inline_refs(defs[key], defs)
        return {k: _inline_refs(v, defs) for k, v in value.items() if k != "$defs"}
    if isinstance(value, list):
        return [_inline_refs(item, defs) for item in value]
    return value


def _distillation_schema() -> dict[str, object]:
    schema = Recipe.model_json_schema()
    properties = cast(dict[str, object], schema["properties"])
    defs = cast(dict[str, object], schema.get("$defs", {}))
    keys = (
        "name",
        "description",
        "recipe_class",
        "action_class",
        "inputs_schema",
        "outputs_schema",
        "instructions",
        "script",
    )
    selected_properties = {key: _inline_refs(properties[key], defs) for key in keys}
    return {
        "type": "object",
        "properties": selected_properties,
        "required": [key for key in keys if key != "script"],
        "additionalProperties": False,
    }


RECIPE_SCHEMA: Final[dict[str, object]] = _distillation_schema()
