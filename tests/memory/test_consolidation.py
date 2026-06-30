from __future__ import annotations

from collections.abc import Sequence

import pytest

from artemis.memory.consolidation import CONSOLIDATION_SCHEMA, LLMConsolidator
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, structured: dict | None) -> None:  # type: ignore[type-arg]
        self.calls: list[tuple[list[Message], str | None, dict | None]] = []  # type: ignore[type-arg]
        self._structured = structured

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = temperature, max_tokens
        self.calls.append((list(messages), model, response_schema))
        return ModelResponse(
            text="",
            model_id=model or "fake",
            structured=self._structured,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


@pytest.mark.asyncio
async def test_llm_consolidator_parses_structured_update_decision() -> None:
    model = FakeModel({"op": "UPDATE", "target": "Ben works at Acme", "reason": "job changed"})
    consolidator = LLMConsolidator(model, model_id="router-model")

    decision = await consolidator.classify("Ben works at Globex", ["Ben works at Acme"])

    assert decision.op == "UPDATE"
    assert decision.target == "Ben works at Acme"
    assert decision.reason == "job changed"
    assert len(model.calls) == 1
    messages, model_id, schema = model.calls[0]
    assert model_id == "router-model"
    assert schema == CONSOLIDATION_SCHEMA
    assert messages[0].role == "system"
    assert messages[1].content == "NEW:\nBen works at Globex\n\nEXISTING:\n- Ben works at Acme"


@pytest.mark.asyncio
async def test_llm_consolidator_empty_existing_adds_without_model_call() -> None:
    model = FakeModel({"op": "NOOP", "target": None, "reason": "would be wrong"})
    consolidator = LLMConsolidator(model)

    decision = await consolidator.classify("Ben works at Globex", [])

    assert decision.op == "ADD"
    assert decision.target is None
    assert decision.reason == "no existing memory"
    assert model.calls == []
