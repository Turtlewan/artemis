---
spec: dev-offline-compose
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: flash
---

# Spec: dev-offline-compose — `compose_brain` adapter overrides + dev FakeEmbedder REPL

**Identity:** Lets `compose_brain` accept optional `embedder` / `model` overrides (default behaviour unchanged — builds the real OpenAI adapters when not supplied) and adds `scripts/dev_chat.py`, a REPL that injects a deterministic `FakeEmbedder` so the responder/tool path can point at an endpoint with **no `/embeddings`** (DeepSeek cloud) or a local server without pulling an embedding model. Combined with `dev-model-auth` this is the decided pre-Mini Tier-2 config (DeepSeek responder + FakeEmbedder).
→ why: validation-slice "dev-runnable brain" enabler (status.md Open Question 2026-06-17). The handoff (2026-06-17) flagged `compose_brain could accept optional adapter overrides for a smoother offline dev experience`.

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->
<!-- Split rule: ONE phase (offline/override composition) across 1 modify (gateway.py) + 1 create (scripts/dev_chat.py) + 1 create (test). Within the 3-file limit. Independent of `dev-model-auth`; build order does not matter. -->

## Assumptions
- Slice 1 is built: `src/artemis/gateway.py` defines `compose_brain(settings: Settings | None = None) -> Brain` which builds `OpenAIEmbeddingModel` + `OpenAIModelPort`, calls `_register_modules(embedder)`, builds `SemanticRouter(registry, embedder)`, returns `Brain(router, registry, model)`. `_register_modules(embedder: object)` already takes the embedder as a param. → impact: Stop (verified against current code 2026-06-17; only the construction of the two adapters becomes conditional).
- The file already has `from __future__ import annotations` and a `TYPE_CHECKING` block importing `ToolRegistry`; new type-only imports go there (no runtime import cost, no cycle). → impact: Low.
- `FakeEmbedder` implements the `EmbeddingModel` port surface used by the registry/router: `dimension` property, `async embed_documents(texts) -> list[Vector]`, `async embed_query(query) -> Vector`. Non-semantic (hash-based) — it proves the loop runs offline; it does NOT give meaningful semantic routing (documented in the script docstring). → impact: Caution (routing quality with fakes is not a goal; the deliverable is the override seam + a runnable REPL).
- `scripts/` is excluded from `mypy`/`ruff src` (per `pyproject.toml`); the dev script need not satisfy `--strict`, but keep it clean. → impact: Low.
- The in-memory tool index does cosine over whatever vectors it is given (it does not enforce `Settings.embedding_dimension`), so a fake of any dimension routes consistently as long as documents and queries use the same fake. → impact: Low.

## Files to change
1. **modify** `src/artemis/gateway.py` — add `embedder` / `model` keyword overrides to `compose_brain`.
2. **create** `scripts/dev_chat.py` — FakeEmbedder + REPL.
3. **create** `tests/test_offline_compose.py` — override-seam coverage.

## Exact changes

### 1. `src/artemis/gateway.py`
Add to the existing `TYPE_CHECKING` block (alongside `ToolRegistry`):
```python
    from artemis.ports.model import ModelPort
    from artemis.ports.retrieval import EmbeddingModel
```

Replace the whole `compose_brain` function body with:
```python
def compose_brain(
    settings: Settings | None = None,
    *,
    embedder: EmbeddingModel | None = None,
    model: ModelPort | None = None,
) -> Brain:
    """Build a wired Brain from settings.

    By default constructs the real adapters (``OpenAIEmbeddingModel``,
    ``OpenAIModelPort``). Pass ``embedder`` and/or ``model`` to inject doubles
    (e.g. a dev ``FakeEmbedder`` for an endpoint with no ``/embeddings``, or a
    fully offline smoke run). Uses lazy ``ToolRegistry.register()`` — no network
    at construction time.
    """
    if settings is None:
        settings = get_settings()

    from artemis.adapters.model_adapters import OpenAIEmbeddingModel, OpenAIModelPort

    if embedder is None:
        embedder = OpenAIEmbeddingModel(settings)
    if model is None:
        model = OpenAIModelPort(settings)

    registry = _register_modules(embedder)
    from artemis.router import SemanticRouter

    router = SemanticRouter(registry, embedder)
    return Brain(router, registry, model)
```

### 2. `scripts/dev_chat.py` (new)
```python
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
```

### 3. `tests/test_offline_compose.py` (new)
```python
"""compose_brain override-seam coverage — runs the brain fully offline."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from artemis.config import Settings
from artemis.gateway import Gateway, compose_brain
from artemis.ports.model import ModelResponse
from artemis.ports.types import Usage


class _FakeEmbedder:
    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * self._dim for _ in texts]

    async def embed_query(self, query: str) -> list[float]:
        return [0.1] * self._dim


class _FakeModel:
    async def complete(self, **kwargs: Any) -> ModelResponse:
        return ModelResponse(
            text="{}",
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            origin="local",
            model_id="fake",
        )

    def complete_stream(self, **kwargs: Any) -> AsyncIterator[str]:
        async def _gen() -> AsyncIterator[str]:
            yield "fake-stream"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]


def test_compose_brain_accepts_overrides() -> None:
    brain = compose_brain(Settings(), embedder=_FakeEmbedder(), model=_FakeModel())
    assert brain is not None


async def test_offline_brain_handles_request_without_network() -> None:
    gateway = Gateway(
        compose_brain(Settings(), embedder=_FakeEmbedder(), model=_FakeModel())
    )
    resp = await gateway.handle_text("what time is it?")
    # Returns *something* (tool result / responder / escalation stub) without raising.
    assert resp.text
```

## Acceptance criteria
1. Overrides threaded → `uv run pytest tests/test_offline_compose.py -q` passes (2 tests; brain builds + a request completes with zero network).
2. Default path unchanged → `uv run pytest -q` still green (all prior tests pass; `compose_brain()` with no overrides builds the real adapters exactly as before).
3. Dev REPL imports + builds offline → `echo "/quit" | uv run python scripts/dev_chat.py` prints the banner and exits 0 (no network, no model server).
4. Types/lint clean → `uv run mypy src` and `uv run ruff check src tests` report no new errors.

## Commands to run
```bash
uv run pytest tests/test_offline_compose.py -q
uv run pytest -q
echo "/quit" | uv run python scripts/dev_chat.py
uv run mypy src
uv run ruff check src tests
```
