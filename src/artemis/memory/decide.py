"""A.U.D.N. decision logic for memory facts.

``AudnDecider`` asks the local sensitive-reasoner role to choose one operation
for one extracted fact against top-k semantic candidates. The JSON shape is
grammar-constrained by ``response_schema`` and still checked here so malformed
output degrades conservatively.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from artemis.memory.extraction import ExtractedFact
from artemis.memory.repository import BitemporalRepository
from artemis.ports.model import ModelPort
from artemis.ports.types import Message

logger = logging.getLogger(__name__)

AudnOp = Literal["ADD", "UPDATE", "DELETE", "NOOP"]

DECISION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE", "NOOP"]},
        "target_fact_id": {"type": ["string", "null"]},
        "object": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["op", "target_fact_id", "object", "confidence"],
    "additionalProperties": False,
}
"""JSON schema for constrained A.U.D.N. decisions."""


@dataclass(frozen=True)
class Candidate:
    """A current fact candidate selected by semantic search."""

    fact_id: str
    subject: str
    relation: str
    object: str


@dataclass(frozen=True)
class AudnDecision:
    """One ADD/UPDATE/DELETE/NOOP decision for an extracted fact."""

    op: AudnOp
    target_fact_id: str | None
    object: str | None
    confidence: float


class AudnDecider:
    """Choose one A.U.D.N. operation for a fact against semantic candidates."""

    def __init__(
        self,
        model: ModelPort,
        repo: BitemporalRepository,
        *,
        role: str = "sensitive_reasoner",
    ) -> None:
        self._model = model
        self._repo = repo
        self._role = role

    async def decide(
        self, new_fact: ExtractedFact, candidates: Sequence[Candidate]
    ) -> AudnDecision:
        """Return a checked model decision, with unsafe target ids downgraded."""
        cardinality = self._repo.cardinality_of(new_fact.relation)
        response = await self._model.complete(
            role=self._role,
            messages=[
                Message(role="system", content=_decision_prompt(cardinality)),
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "new_fact": {
                                "subject": new_fact.subject,
                                "relation": new_fact.relation,
                                "object": new_fact.object,
                                "confidence": new_fact.confidence,
                                "contextual_description": new_fact.contextual_description,
                            },
                            "candidates": [
                                {
                                    "fact_id": c.fact_id,
                                    "subject": c.subject,
                                    "relation": c.relation,
                                    "object": c.object,
                                }
                                for c in candidates
                            ],
                            "cardinality": cardinality,
                        },
                        separators=(",", ":"),
                    ),
                ),
            ],
            response_schema=DECISION_SCHEMA,
            temperature=0.0,
        )
        try:
            decision = validate_decision_payload(json.loads(response.text))
        except Exception as exc:
            logger.warning("Memory A.U.D.N. decision parse failed (%s)", type(exc).__name__)
            return AudnDecision("NOOP", None, None, 0.0)

        return downgrade_unknown_target(decision, candidates)


class FakeDecider:
    """Deterministic A.U.D.N. rubric for tests."""

    async def decide(
        self, new_fact: ExtractedFact, candidates: Sequence[Candidate]
    ) -> AudnDecision:
        delete_requested = (
            new_fact.contextual_description is not None
            and "DELETE" in new_fact.contextual_description.upper()
        )
        same_key_candidates = [
            candidate
            for candidate in candidates
            if candidate.subject == new_fact.subject and candidate.relation == new_fact.relation
        ]

        if delete_requested:
            target = _matching_object(new_fact, same_key_candidates) or _first_or_none(
                same_key_candidates
            )
            if target is None:
                return AudnDecision("NOOP", None, None, new_fact.confidence)
            return AudnDecision("DELETE", target.fact_id, None, new_fact.confidence)

        identical = _matching_object(new_fact, same_key_candidates)
        if identical is not None:
            return AudnDecision("NOOP", identical.fact_id, None, new_fact.confidence)

        target = _first_or_none(same_key_candidates)
        if target is not None:
            return AudnDecision("UPDATE", target.fact_id, new_fact.object, new_fact.confidence)

        return AudnDecision("ADD", None, new_fact.object, new_fact.confidence)


def validate_decision_payload(payload: object) -> AudnDecision:
    """Validate parsed model JSON into an ``AudnDecision``."""
    if not isinstance(payload, dict):
        raise ValueError("decision payload must be an object")
    op = payload.get("op")
    target_fact_id = payload.get("target_fact_id")
    object_ = payload.get("object")
    confidence = payload.get("confidence")

    if op not in ("ADD", "UPDATE", "DELETE", "NOOP"):
        raise ValueError("decision op is invalid")
    if target_fact_id is not None and not isinstance(target_fact_id, str):
        raise ValueError("decision target_fact_id must be a string or null")
    if object_ is not None and not isinstance(object_, str):
        raise ValueError("decision object must be a string or null")
    if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("decision confidence must be between 0 and 1")

    checked_op: AudnOp = op
    return AudnDecision(
        op=checked_op,
        target_fact_id=target_fact_id,
        object=object_.strip() if object_ else None,
        confidence=float(confidence),
    )


def downgrade_unknown_target(
    decision: AudnDecision, candidates: Sequence[Candidate]
) -> AudnDecision:
    """Downgrade UPDATE/DELETE decisions that reference a non-candidate id."""
    if decision.op not in ("UPDATE", "DELETE"):
        return decision
    candidate_ids = {candidate.fact_id for candidate in candidates}
    if decision.target_fact_id in candidate_ids:
        return decision

    logger.warning("Memory A.U.D.N. decision referenced an unknown target id")
    if decision.op == "UPDATE":
        return AudnDecision("ADD", None, decision.object, decision.confidence)
    return AudnDecision("NOOP", None, None, decision.confidence)


def _decision_prompt(cardinality: str) -> str:
    return (
        "Choose one memory write operation for a single extracted fact. "
        "ADD when no candidate already states the fact. UPDATE when a SINGLE relation has "
        "the same subject and relation but a different object. DELETE only when the new fact "
        "explicitly negates or supersedes a candidate. NOOP when a candidate already states it. "
        f"The relation cardinality is {cardinality}. For MULTI relations, different objects "
        "normally coexist as ADD rather than UPDATE."
    )


def _matching_object(new_fact: ExtractedFact, candidates: Sequence[Candidate]) -> Candidate | None:
    for candidate in candidates:
        if candidate.object.casefold() == new_fact.object.casefold():
            return candidate
    return None


def _first_or_none(candidates: Sequence[Candidate]) -> Candidate | None:
    return candidates[0] if candidates else None
