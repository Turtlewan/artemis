"""Atomic fact extraction for the memory write path.

The real extractor uses the ``ModelPort`` constrained-output seam by passing
``EXTRACTION_SCHEMA`` as ``response_schema``. The adapter enforces the grammar;
this module still validates the returned JSON and degrades to an empty fact
list if the model returns malformed data.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace

from artemis.ports.model import ModelPort
from artemis.ports.types import Message
from artemis.sensitivity import Sensitivity, SensitivityClassifierProtocol

logger = logging.getLogger(__name__)

EXTRACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "relation": {"type": "string"},
                    "object": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "contextual_description": {"type": ["string", "null"]},
                },
                "required": ["subject", "relation", "object", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}
"""JSON schema for constrained atomic-fact extraction."""


@dataclass(frozen=True)
class ExtractedFact:
    """An owner-scoped atomic fact extracted from a turn.

    Facts inherit the source sensitivity when available. Otherwise extraction
    classifies the whole source text once per call, fail-closed to
    ``"sensitive"``. Residual sensitive memory covers journal, credential, and
    identity facts; ``category`` is reserved and remains ``None`` in v1.
    """

    subject: str
    relation: str
    object: str
    confidence: float
    keywords: tuple[str, ...] = ()
    contextual_description: str | None = None
    sensitivity: Sensitivity = "sensitive"
    category: str | None = None


class FactExtractor:
    """Extract atomic owner facts through the local sensitive-reasoner role."""

    def __init__(
        self,
        model: ModelPort,
        *,
        role: str = "sensitive_reasoner",
        classifier: SensitivityClassifierProtocol | None = None,
    ) -> None:
        self._model = model
        self._role = role
        self._classifier = classifier

    async def extract(
        self,
        text: str,
        *,
        context: str | None = None,
        source_sensitivity: Sensitivity | None = None,
    ) -> list[ExtractedFact]:
        """Return schema-validated extracted facts, or ``[]`` on parse failure."""
        prompt = (
            "Extract atomic, self-contained (subject, relation, object) facts about the owner "
            "from the text. For first-person statements, use subject 'owner'. Do not infer "
            "unstated facts. Return only facts that are explicit in the text."
        )
        if context:
            prompt += "\nUse this context only to resolve direct references: " + context

        response = await self._model.complete(
            role=self._role,
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=text),
            ],
            response_schema=EXTRACTION_SCHEMA,
            temperature=0.0,
        )
        try:
            payload = json.loads(response.text)
            facts = validate_extraction_payload(payload)
        except Exception as exc:
            logger.warning("Memory extraction parse failed (%s)", type(exc).__name__)
            return []
        tag = await self._resolve_sensitivity(text, source_sensitivity=source_sensitivity)
        return [replace(fact, sensitivity=tag, category=None) for fact in facts]

    async def _resolve_sensitivity(
        self, text: str, *, source_sensitivity: Sensitivity | None
    ) -> Sensitivity:
        if source_sensitivity is not None:
            return source_sensitivity
        if self._classifier is None:
            return "sensitive"
        try:
            return await self._classifier.classify(text)
        except Exception as exc:
            logger.warning("Memory sensitivity classification failed (%s)", type(exc).__name__)
            return "sensitive"


class FakeExtractor:
    """Small deterministic extractor for off-hardware tests."""

    async def extract(
        self,
        text: str,
        *,
        context: str | None = None,
        source_sensitivity: Sensitivity | None = None,
    ) -> list[ExtractedFact]:
        del context
        tag = source_sensitivity or "sensitive"
        normalized = text.strip()
        lowered = normalized.lower()

        delete_match = re.search(
            r"(?:do not|don't|no longer) live in (?P<place>[A-Za-z][A-Za-z .'-]*?)(?: anymore)?$",
            normalized,
            re.IGNORECASE,
        )
        if delete_match:
            return [
                ExtractedFact(
                    "owner",
                    "lives_in",
                    _clean_object(delete_match.group("place")),
                    0.95,
                    contextual_description="DELETE",
                    sensitivity=tag,
                    category=None,
                )
            ]

        moved_match = re.search(
            r"(?:moved to|live in) (?P<place>[A-Za-z][A-Za-z .'-]*?)$",
            normalized,
            re.IGNORECASE,
        )
        if moved_match:
            return [
                ExtractedFact(
                    "owner",
                    "lives_in",
                    _clean_object(moved_match.group("place")),
                    0.95,
                    sensitivity=tag,
                    category=None,
                )
            ]

        like_match = re.search(
            r"\bI like (?P<thing>[A-Za-z][A-Za-z .'-]*?)$", normalized, re.IGNORECASE
        )
        if like_match:
            return [
                ExtractedFact(
                    "owner",
                    "likes",
                    _clean_object(like_match.group("thing")),
                    0.9,
                    sensitivity=tag,
                    category=None,
                )
            ]

        if "used to" in lowered:
            used_to_match = re.search(
                r"used to (?P<relation>like|live in) (?P<object>[A-Za-z][A-Za-z .'-]*?)$",
                normalized,
                re.IGNORECASE,
            )
            if used_to_match:
                relation = (
                    "likes" if used_to_match.group("relation").lower() == "like" else "lives_in"
                )
                return [
                    ExtractedFact(
                        "owner",
                        relation,
                        _clean_object(used_to_match.group("object")),
                        0.9,
                        contextual_description="DELETE",
                        sensitivity=tag,
                        category=None,
                    )
                ]

        return []


def validate_extraction_payload(payload: object) -> list[ExtractedFact]:
    """Validate parsed model JSON into ``ExtractedFact`` values."""
    if not isinstance(payload, dict):
        raise ValueError("extraction payload must be an object")
    facts = payload.get("facts")
    if not isinstance(facts, list):
        raise ValueError("extraction facts must be a list")

    extracted: list[ExtractedFact] = []
    for fact in facts:
        if not isinstance(fact, dict):
            raise ValueError("extracted fact must be an object")

        subject = fact.get("subject")
        relation = fact.get("relation")
        object_ = fact.get("object")
        confidence = fact.get("confidence")
        keywords = fact.get("keywords", [])
        contextual_description = fact.get("contextual_description")

        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("extracted subject must be a non-empty string")
        if not isinstance(relation, str) or not relation.strip():
            raise ValueError("extracted relation must be a non-empty string")
        if not isinstance(object_, str) or not object_.strip():
            raise ValueError("extracted object must be a non-empty string")
        if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("extracted confidence must be between 0 and 1")
        if not isinstance(keywords, list) or not all(isinstance(item, str) for item in keywords):
            raise ValueError("extracted keywords must be strings")
        if contextual_description is not None and not isinstance(contextual_description, str):
            raise ValueError("extracted contextual_description must be a string or null")

        extracted.append(
            ExtractedFact(
                subject=subject.strip(),
                relation=relation.strip(),
                object=object_.strip(),
                confidence=float(confidence),
                keywords=tuple(item.strip() for item in keywords if item.strip()),
                contextual_description=(
                    contextual_description.strip() if contextual_description else None
                ),
            )
        )

    return extracted


def _clean_object(value: str) -> str:
    """Trim common trailing punctuation from a regex-captured object."""
    return value.strip().rstrip(".!,")
