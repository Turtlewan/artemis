from __future__ import annotations

from collections.abc import Sequence

import pytest

from artemis.memory.summarize import LLMSummarizer
from artemis.types import MemoryItem, Message, ModelResponse, Usage


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[tuple[list[Message], str | None, dict | None]] = []  # type: ignore[type-arg]

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
            text=" merged summary ",
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


@pytest.mark.asyncio
async def test_llm_summarizer_returns_stripped_model_text_and_lists_items() -> None:
    model = FakeModel()
    summarizer = LLMSummarizer(model, model_id="small-model")
    items = [
        MemoryItem(content="first fact", layer="semantic"),
        MemoryItem(content="second fact", layer="episodic"),
    ]

    result = await summarizer.summarize(items, query="q")

    assert result == "merged summary"
    assert len(model.calls) == 1
    messages, model_id, schema = model.calls[0]
    assert model_id == "small-model"
    assert schema is None
    assert messages[0].role == "system"
    assert messages[1] == Message(
        role="user",
        content="Query: q\n\nItems:\n- first fact\n- second fact",
    )
