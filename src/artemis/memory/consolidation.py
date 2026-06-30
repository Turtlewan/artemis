"""Memory consolidation decisions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel

from artemis.ports.model import ModelPort
from artemis.types import Message

ConsolidationOp = Literal["ADD", "UPDATE", "DELETE", "NOOP"]


class ConsolidationDecision(BaseModel):
    op: ConsolidationOp
    target: str | None = None
    reason: str = ""


CONSOLIDATION_SCHEMA: dict = {  # type: ignore[type-arg]
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE", "NOOP"]},
        "target": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["op", "target", "reason"],
}


class Consolidator(Protocol):
    async def classify(self, new: str, existing: Sequence[str]) -> ConsolidationDecision: ...


class LLMConsolidator:
    def __init__(self, model: ModelPort, *, model_id: str | None = None) -> None:
        self._model = model
        self._model_id = model_id

    async def classify(self, new: str, existing: Sequence[str]) -> ConsolidationDecision:
        if not existing:
            return ConsolidationDecision(op="ADD", reason="no existing memory")
        listing = "\n".join(f"- {e}" for e in existing)
        system = (
            "You maintain a memory store. Decide how a NEW fact relates to EXISTING facts. "
            "ADD = genuinely new; UPDATE = supersedes/refines one existing fact (set target to that "
            "fact verbatim); DELETE = negates one existing fact (set target); NOOP = already known. "
            "Return only the JSON."
        )
        response = await self._model.complete(
            messages=[
                Message(role="system", content=system),
                Message(role="user", content=f"NEW:\n{new}\n\nEXISTING:\n{listing}"),
            ],
            response_schema=CONSOLIDATION_SCHEMA,
            model=self._model_id,
        )
        data = response.structured or {"op": "ADD", "target": None, "reason": "fallback"}
        return ConsolidationDecision.model_validate(data)
