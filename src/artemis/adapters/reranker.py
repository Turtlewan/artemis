"""Qwen3 reranker adapter behind the Reranker port."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from artemis.adapters.model_adapters import OpenAIModelPort
from artemis.config import Settings, get_settings
from artemis.ports.model import ModelPort
from artemis.ports.retrieval import Reranker
from artemis.ports.types import Message, RetrievedChunk

_TOKEN_RE = re.compile(r"\w+")


class QwenReranker:
    """Score candidate chunks via the local ``reranker`` ModelPort role."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model: ModelPort | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._model = model or OpenAIModelPort(self._settings)

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Return chunks sorted by descending cross-encoder relevance."""
        if top_k <= 0 or not chunks:
            return []

        scores = await self._score(query, [chunk.chunk.text for chunk in chunks])
        if len(scores) != len(chunks):
            raise ValueError("reranker returned a score count that does not match chunks")

        rescored = [
            RetrievedChunk(chunk=chunk.chunk, score=score) for chunk, score in zip(chunks, scores)
        ]
        return sorted(
            rescored,
            key=lambda item: (-item.score, item.chunk.chunk_id),
        )[:top_k]

    async def _score(self, query: str, texts: Sequence[str]) -> list[float]:
        """Use constrained chat completions to score relevance in input order."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": len(texts),
                    "maxItems": len(texts),
                }
            },
            "required": ["scores"],
            "additionalProperties": False,
        }
        candidate_lines = "\n".join(f"{index}. {text}" for index, text in enumerate(texts, start=1))
        response = await self._model.complete(
            role="reranker",
            messages=[
                Message(
                    "system",
                    "Return only JSON with a scores array. Each score is a relevance "
                    "number from 0 to 1 for the matching candidate.",
                ),
                Message(
                    "user",
                    f"Query:\n{query}\n\nCandidates:\n{candidate_lines}",
                ),
            ],
            response_schema=schema,
            temperature=0.0,
        )
        payload = json.loads(response.text)
        raw_scores = payload.get("scores")
        if not isinstance(raw_scores, list):
            raise ValueError("reranker response missing scores list")
        return [float(score) for score in raw_scores]


class FakeReranker:
    """Deterministic lexical-overlap reranker for off-hardware tests."""

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if top_k <= 0:
            return []
        query_tokens = set(_TOKEN_RE.findall(query.lower()))
        rescored = [
            RetrievedChunk(
                chunk=chunk.chunk,
                score=float(len(query_tokens & set(_TOKEN_RE.findall(chunk.chunk.text.lower())))),
            )
            for chunk in chunks
        ]
        return sorted(
            rescored,
            key=lambda item: (-item.score, item.chunk.chunk_id),
        )[:top_k]


_check: Reranker = QwenReranker()
