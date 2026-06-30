from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingPort(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text, order-aligned."""
        ...
