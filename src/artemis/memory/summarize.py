"""Summarization helpers for retrieved memory overflow."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from artemis.ports.model import ModelPort
from artemis.types import MemoryItem, Message


class Summarizer(Protocol):
    async def summarize(self, items: Sequence[MemoryItem], *, query: str) -> str: ...


class LLMSummarizer:
    def __init__(self, model: ModelPort, *, model_id: str | None = None) -> None:
        self._model = model
        self._model_id = model_id

    async def summarize(self, items: Sequence[MemoryItem], *, query: str) -> str:
        bullets = "\n".join(f"- {item.content}" for item in items)
        system = (
            "Compress the memory items into a few dense sentences, keeping only what is relevant "
            "to the user's query. No preamble."
        )
        response = await self._model.complete(
            messages=[
                Message(role="system", content=system),
                Message(role="user", content=f"Query: {query}\n\nItems:\n{bullets}"),
            ],
            model=self._model_id,
        )
        return response.text.strip()
