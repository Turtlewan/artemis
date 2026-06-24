"""Dev chat REPL — runs the brain with a deterministic FakeEmbedder.

Lets the responder/tool path point at an authed cloud endpoint that has no
``/embeddings`` (e.g. DeepSeek — set ARTEMIS_MODEL_API_KEY and point
config/roles.toml [responder] at it) or a local server, without needing a real
embedding model. The FakeEmbedder is NON-SEMANTIC (hash-based): it proves the
brain loop runs offline; it does not give meaningful semantic routing.

Usage::

    ARTEMIS_MODEL_API_KEY=sk-... uv run python scripts/dev_chat.py
    uv run python scripts/dev_chat.py --real   # real local embedder (Ollama, per roles.toml)

Without ``--real`` the brain runs with the non-semantic FakeEmbedder (offline).
With ``--real`` it composes the default real ``OpenAIEmbeddingModel``, which
config/roles.toml [embedder] points at Ollama on this dev box — see
docs/bring-up/DEV-MODEL-STACK.md for the install + model pulls.
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

    async def embed_documents(self, texts: Sequence[str]) -> list[Sequence[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._vec(query)

    def _vec(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = (digest * (self._dim // len(digest) + 1))[: self._dim]
        return [b / 127.5 - 1.0 for b in raw]


async def _repl(*, real: bool) -> None:
    settings = get_settings()
    if real:
        # Real local embedder (default compose_brain path → OpenAIEmbeddingModel,
        # pointed at Ollama via config/roles.toml [embedder]). See DEV-MODEL-STACK.md.
        gateway = Gateway(compose_brain(settings))
        label = "real Ollama embedder"
    else:
        gateway = Gateway(
            compose_brain(settings, embedder=FakeEmbedder(settings.embedding_dimension))
        )
        label = "FakeEmbedder"
    print(f"Artemis dev chat ({label}) — type a question, /quit to exit.", flush=True)
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
    asyncio.run(_repl(real="--real" in sys.argv[1:]))
