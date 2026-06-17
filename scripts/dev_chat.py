"""Dev chat REPL — runs the brain with a deterministic FakeEmbedder.

Lets the responder/tool path point at an authed cloud endpoint that has no
``/embeddings`` (e.g. DeepSeek — set ARTEMIS_MODEL_API_KEY and point
config/roles.toml [responder] at it) or a local server, without needing a real
embedding model. The FakeEmbedder is NON-SEMANTIC (hash-based): it proves the
brain loop runs offline; it does not give meaningful semantic routing.

Usage::

    ARTEMIS_MODEL_API_KEY=sk-... uv run python scripts/dev_chat.py

(Edit config/roles.toml [responder] endpoint/model_id first.)
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from collections.abc import Sequence

from artemis.config import get_settings
from artemis.gateway import Gateway, compose_brain


class FakeEmbedder:
    """Deterministic hash-based embedder (non-semantic; offline)."""

    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._vec(query)

    def _vec(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = (digest * (self._dim // len(digest) + 1))[: self._dim]
        return [b / 127.5 - 1.0 for b in raw]


async def _repl() -> None:
    settings = get_settings()
    gateway = Gateway(
        compose_brain(settings, embedder=FakeEmbedder(settings.embedding_dimension))
    )
    print("Artemis dev chat (FakeEmbedder) — type a question, /quit to exit.", flush=True)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line == "/quit":
            break
        async for chunk in gateway.handle_text_stream(line):
            print(chunk, end="", flush=True)
        print(flush=True)


if __name__ == "__main__":
    asyncio.run(_repl())
