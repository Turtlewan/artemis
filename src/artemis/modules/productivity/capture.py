"""Commitment capture and capture-recipe graduation for productivity."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from artemis.modules.productivity.store import ProductivityStore
from artemis.ports.model import ModelPort, ModelResponse
from artemis.ports.types import Message, Vector
from artemis.recipes import ActionClass, Promoter, Recipe, RecipeClass, RecipeStatus, RecipeStore
from artemis.untrusted import QuarantinedReader

LOGGER = logging.getLogger(__name__)

COMMITMENT_SHAPES = {
    "will_send",
    "will_call",
    "will_meet",
    "will_pay",
    "will_review",
    "will_schedule",
    "will_complete",
    "other",
}

COMMITMENT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["is_commitment", "title", "commitment_shape"],
    "properties": {
        "is_commitment": {"type": "boolean"},
        "title": {"type": "string", "maxLength": 200},
        "due": {"type": ["string", "null"], "description": "ISO date or null"},
        "commitment_shape": {
            "type": "string",
            "enum": [
                "will_send",
                "will_call",
                "will_meet",
                "will_pay",
                "will_review",
                "will_schedule",
                "will_complete",
                "other",
            ],
        },
    },
    "additionalProperties": False,
}


class FakeCommitmentDetector:
    """Deterministic test detector that satisfies ``ModelPort``."""

    last_user_content: str | None = None

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, response_schema, temperature, max_tokens
        user_content = messages[-1].content
        self.last_user_content = user_content
        lowered = user_content.lower()
        if "not a task" in lowered or not lowered.strip():
            payload = {"is_commitment": False, "title": "", "commitment_shape": "other"}
        else:
            shape = "other"
            title = user_content.strip()[:200] or "Captured commitment"
            if "send" in lowered or "forward" in lowered:
                shape = "will_send"
                title = "Send the report"
            elif "call" in lowered:
                shape = "will_call"
                title = "Call"
            elif "meet" in lowered:
                shape = "will_meet"
                title = "Meet"
            payload = {
                "is_commitment": True,
                "title": title,
                "due": None,
                "commitment_shape": shape,
            }
        return ModelResponse(text=json.dumps(payload), origin="local", model_id="fake")

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature
        raise NotImplementedError

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


@dataclass
class CaptureService:
    """Detect inert task suggestions and graduate recurring capture patterns."""

    store: ProductivityStore
    model: ModelPort
    quarantine: QuarantinedReader | None
    recipe_store: RecipeStore
    promoter: Promoter
    role: str = "sensitive_reasoner"

    async def suggest_from_text(
        self,
        source: Literal["chat", "email", "calendar"],
        text: str,
        *,
        untrusted: bool = False,
    ) -> str | None:
        """Create an inert suggestion when bounded detection finds a commitment.

        Email capture is quarantine-first: raw email text never reaches the
        privileged detection model or the productivity database.
        """
        detection_input = text
        if untrusted:
            if self.quarantine is None:
                raise ValueError("quarantine required for untrusted source")
            extract = await self.quarantine.read(
                raw_content=text,
                source_url="",
                source_domain="email",
                query="task commitments",
            )
            if extract.parse_failed:
                LOGGER.warning("Commitment capture skipped after quarantine parse failure")
                return None
            detection_input = extract.summary

        resp = await self.model.complete(
            role=self.role,
            messages=[
                Message(
                    role="system",
                    content="Extract task commitments from the following text. Respond in JSON.",
                ),
                Message(role="user", content=detection_input),
            ],
            response_schema=COMMITMENT_SCHEMA,
        )
        try:
            detected = json.loads(resp.text)
        except json.JSONDecodeError:
            return None
        if not isinstance(detected, dict) or detected.get("is_commitment") is not True:
            return None

        title = detected.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        commitment_shape = detected.get("commitment_shape", "other")
        if not isinstance(commitment_shape, str):
            commitment_shape = "other"

        # SECURITY: raw email text (the text arg when untrusted=True) is NEVER passed to
        # store.create_suggestion or to the extraction model. Only Extract.summary reaches the
        # detection model. raw_context is always None.
        return self.store.create_suggestion(
            title=title[:200],
            notes=None,
            source=source,
            raw_context=None,
            commitment_shape=commitment_shape,
        )

    async def accept_with_graduation(
        self,
        suggestion_id: str,
        *,
        project_id: str | None = None,
        area_id: str | None = None,
        due_at: str | None = None,
    ) -> str:
        """Accept a suggestion, then create a gated recipe candidate at threshold."""
        del area_id
        suggestion = self.store.get_suggestion(suggestion_id)
        if suggestion is None:
            raise KeyError(suggestion_id)
        source_class = str(suggestion.get("source") or "other")
        commitment_shape = str(suggestion.get("commitment_shape") or "other")

        task_id = self.store.accept_suggestion(
            suggestion_id,
            project_id=project_id,
            due_at=due_at,
        )
        capture_key = build_capture_pattern_key(source_class, commitment_shape)

        count_before = self.promoter.recurrence.count(capture_key)
        self.promoter.recurrence.note(capture_key)
        new_count = count_before + 1

        if new_count >= self.promoter.threshold:
            all_for_key = [
                recipe
                for recipe in self.recipe_store.list()
                if recipe.task_class_key == capture_key
            ]
            if not all_for_key:
                candidate = _build_capture_recipe(capture_key, source_class, commitment_shape)
                await self.recipe_store.write(candidate)
                await self.promoter.note_occurrence(capture_key)

        return task_id


def build_capture_pattern_key(source_class: str, commitment_shape: str) -> str:
    """Return the stable recurrence key for a source bucket and commitment shape."""
    safe_source = source_class.strip().lower()
    safe_shape = commitment_shape.strip().lower()
    if safe_source not in {"email", "chat", "calendar"}:
        safe_source = "other"
    if safe_shape not in COMMITMENT_SHAPES:
        safe_shape = "other"
    return f"{safe_source}:{safe_shape}"


def _build_capture_recipe(capture_key: str, source_class: str, commitment_shape: str) -> Recipe:
    """Build a gated TOUCHES_DATA recipe candidate for recurring capture."""
    safe_source = source_class.strip().lower()
    safe_shape = commitment_shape.strip().lower()
    return Recipe(
        name=f"capture_{capture_key.replace(':', '_')}",
        description=(
            f"Auto-capture {safe_shape.replace('_', ' ')} commitments from {safe_source} "
            "into task suggestions"
        ),
        version="0.1.0",
        recipe_class=RecipeClass.INSTRUCTIONS,
        action_class=ActionClass.TOUCHES_DATA,
        task_class_key=capture_key,
        inputs_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["source", "text"],
        },
        outputs_schema={
            "type": "object",
            "properties": {"suggestion_id": {"type": "string"}},
        },
        instructions=(
            f"When a {safe_shape.replace('_', ' ')} commitment is detected in a "
            f"{safe_source} message, automatically call suggest_from_text("
            f"source='{safe_source}', text=<text>, "
            f"untrusted={'true' if safe_source == 'email' else 'false'}) and create an inert "
            "suggestion. The owner reviews and accepts it from the suggestion inbox."
        ),
        status=RecipeStatus.CANDIDATE,
        provenance={"origin": "productivity_capture"},
    )


def _commitment_shape_values() -> set[str]:
    values = cast(dict[str, object], COMMITMENT_SCHEMA["properties"])["commitment_shape"]
    enum_values = cast(dict[str, object], values)["enum"]
    return {str(value) for value in cast(list[object], enum_values)}
