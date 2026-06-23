---
spec: composite-model-routing
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: flash
depends_on: codex-model-adapter
---

# Spec: composite-model-routing — dispatch ModelPort by role-adapter, fall back to local

**Identity:** Add a `CompositeModelPort` that dispatches each `ModelPort` call to the adapter named by the role's `adapter` field in `roles.toml` (`codex` → ChatGPT-subscription Codex, else → local OpenAI-compatible), with **automatic fallback to a local role on any Codex failure**, and wire it into `compose_brain`. This is the pluggable seam + fallback of ADR-022. The `Brain` is unchanged — it still calls `self._model.complete(role=...)`.
→ why: ADR-022 (pluggable reasoning seam; Codex default with local/API fallback — the fallback is mandatory, not optional).

<!-- Execution script. Build AFTER `codex-model-adapter`. 5 files, one phase (the dispatch seam + its wiring). Embeddings always route local. -->

## Assumptions
- `codex-model-adapter` is built: `CodexModelPort` exists in `src/artemis/adapters/codex_adapter.py`; `config.py` has `codex_binary`/`codex_model` and `"codex"` in the `ModelRole.adapter` Literal. → impact: Stop (this spec depends on it).
- `compose_brain` (`src/artemis/gateway.py:61`) builds the default model at line 83 `model = OpenAIModelPort(settings)` and keeps a `model: ModelPort | None = None` injection param for test doubles. → impact: Stop (replace only the default construction; keep the injection param so dev/offline composes still work).
- `OpenAIModelPort.embed` is the real embeddings path; Codex has no embeddings. → impact: Stop (composite `embed` always delegates to the local adapter).
- A role whose `roles.toml` `adapter` is `codex` is a *cloud* role; everything else is *local*. This spec does NOT decide which requests are sensitive (that is `brain-sensitivity-routing`) — it only routes by the role it is handed. → impact: Stop (no sensitivity logic here).
- The local fallback's `ModelResponse.origin` is `"local"` (vs the `"cloud"` a successful Codex call returns), so callers/telemetry can detect the degraded path **from the response itself**; the `DEGRADED:` WARNING is the operator signal. → impact: Low. [apex-security FLAG]
- The fallback role (`sensitive_reasoner`) is a normal local role that accepts the **same `Sequence[Message]`** shape — no re-shaping needed; `messages`/`response_schema` flow to it unchanged. → impact: Stop. [apex-security FLAG]

## Files to change
1. **create** `src/artemis/adapters/composite_model.py` — `CompositeModelPort`.
2. **modify** `src/artemis/config.py` — add `codex_fallback_role: str = "sensitive_reasoner"` to `Settings`.
3. **modify** `config/roles.toml` — add a `responder_cloud` role (adapter = `codex`). Do NOT repoint `responder` (default stays local until `brain-sensitivity-routing` routes deliberately).
4. **modify** `src/artemis/gateway.py` — in `compose_brain`, build `CompositeModelPort(settings)` as the default model instead of `OpenAIModelPort(settings)`.
5. **create** `tests/test_composite_model.py` — dispatch + fallback tests with fakes.
6. **modify** `tests/test_config.py` — teach the `test_roles_toml_structure` guardrail about the new role: add `responder_cloud` to `expected_roles` and `"codex"` to the allowed-adapter tuple. (Amendment 2026-06-23 — build surfaced that this exact-match guardrail locks `roles.toml`'s role set + adapter allow-list; the deliberate new `codex` role must be reflected here. Not weakening a test — updating an allow-list to match a reviewed change.)

## Exact changes

### 1. `src/artemis/adapters/composite_model.py` (new)
```python
"""CompositeModelPort — dispatch a ModelPort call to the adapter named by the
role's `adapter` field (roles.toml). codex roles run on the ChatGPT subscription
and fall back to a local role on failure (ADR-022). Embeddings always local."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence

from artemis.adapters.codex_adapter import CodexModelPort
from artemis.adapters.model_adapters import OpenAIModelPort
from artemis.config import Settings, get_settings
from artemis.ports.model import ModelPort, ModelResponse
from artemis.ports.types import Message, Vector

logger = logging.getLogger(__name__)


class CompositeModelPort:
    """Route ModelPort calls by role-adapter; Codex falls back to local."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        local: ModelPort | None = None,
        codex: ModelPort | None = None,
    ) -> None:
        self._settings: Settings = settings or get_settings()
        self._local: ModelPort = local or OpenAIModelPort(self._settings)
        self._codex: ModelPort = codex or CodexModelPort(self._settings)
        self._fallback_role = self._settings.codex_fallback_role   # typed (no getattr bypass)

    def _is_codex_role(self, role: str) -> bool:
        cfg = self._settings.roles.get(role)
        return bool(cfg and cfg.adapter == "codex")

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        if self._is_codex_role(role):
            try:
                return await self._codex.complete(
                    role=role, messages=messages, response_schema=response_schema,
                    temperature=temperature, max_tokens=max_tokens,
                )
            except Exception:
                # DEGRADED: content-free log (no exc_info — the exception body could carry
                # context; the adapter already scrubs its message). Visibly marks the
                # degraded-to-local path so an auth/outage failure is observable.
                # [apex-security BLOCK + FLAG]
                logger.warning(
                    "DEGRADED: Codex unavailable for role %s — serving from local fallback %s",
                    role, self._fallback_role,
                )
                return await self._local.complete(
                    role=self._fallback_role, messages=messages, response_schema=response_schema,
                    temperature=temperature, max_tokens=max_tokens,
                )
        return await self._local.complete(
            role=role, messages=messages, response_schema=response_schema,
            temperature=temperature, max_tokens=max_tokens,
        )

    def complete_stream(
        self, *, role: str, messages: Sequence[Message], temperature: float = 0.7
    ) -> AsyncIterator[str]:
        async def _stream() -> AsyncIterator[str]:
            # Codex roles: route through complete() (single-shot + built-in fallback) and
            # yield once. This AVOIDS a split stream — Codex has no real token stream, and a
            # mid-generator try/except fallback could interleave two sources if Codex ever
            # raised after the first chunk. [apex-python BLOCK]
            if self._is_codex_role(role):
                resp = await self.complete(role=role, messages=messages, temperature=temperature)
                yield resp.text
                return
            # Local roles stream natively.
            async for chunk in self._local.complete_stream(
                role=role, messages=messages, temperature=temperature
            ):
                yield chunk

        return _stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return await self._local.embed(role, texts)   # embeddings stay local (ADR-022)
```

### 2. `src/artemis/config.py` (modify)
Add to `Settings`:
```python
    codex_fallback_role: str = "sensitive_reasoner"
```

### 3. `config/roles.toml` (modify)
Append a cloud role (the local `responder` + `sensitive_reasoner` stay as-is):
```toml
[responder_cloud]
endpoint = "codex"           # logical role — Codex uses the CLI/subscription, not an HTTP endpoint
model_id = "gpt-5.4"         # informational; CodexModelPort uses settings.codex_model (per-role cloud model is a follow-up)
adapter = "codex"
```

### 4. `src/artemis/gateway.py` (modify)
In `compose_brain`, replace the default model construction:
- **From:** `if model is None:\n        model = OpenAIModelPort(settings)`
- **To:** `if model is None:\n        from artemis.adapters.composite_model import CompositeModelPort\n        model = CompositeModelPort(settings)`
Keep the existing `from artemis.adapters.model_adapters import OpenAIEmbeddingModel, OpenAIModelPort` import (still used for `embedder` + inside the composite). Leave the `model` injection param + everything else unchanged.

### 5. `tests/test_composite_model.py` (new)
With fake `local` and `codex` ModelPorts injected (record calls; codex can be set to raise), and a `Settings` whose `roles` includes a `responder_cloud` (adapter=codex), a `responder` (adapter=openai), and a `sensitive_reasoner` (adapter=openai):
- `complete(role="responder_cloud")` → routed to the codex fake (assert codex called, local not).
- `complete(role="responder")` → routed to the local fake.
- `complete(role="responder_cloud")` when the codex fake raises → falls back to `local.complete(role="sensitive_reasoner")` (assert local called with the fallback role; result returned, no exception).
- `complete_stream(role="responder_cloud")` with codex raising → streams from local fallback.
- `embed(role="embedder")` → always delegates to local.
- **Protocol conformance:** `isinstance(CompositeModelPort(settings, local=fake, codex=fake), ModelPort)` is `True`.

## Acceptance criteria
1. **Dispatch by adapter** → `uv run --frozen pytest tests/test_composite_model.py -q` passes the route-to-codex and route-to-local cases.
2. **Fallback works** → the codex-raises case returns a `ModelResponse` from the local fallback role, no exception propagated.
3. **Embeddings local** → composite `embed` calls the local adapter only.
4. **Brain unchanged** → `uv run --frozen pytest -q` full suite stays green (the Brain still calls `role="responder"`, which `roles.toml` maps to the local adapter — behaviour identical to before this spec).
5. **Type/lint** → `uv run --frozen mypy` clean (CompositeModelPort satisfies `ModelPort`); `ruff check .` + `ruff format --check .` clean.
6. **Surgical** → `git diff --stat` shows only the 5 files above.

## Commands to run
```bash
uv sync
uv run --frozen ruff format .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest tests/test_composite_model.py -q
uv run --frozen pytest -q
```

## Progress
_(Coding mode writes here — do not edit manually)_
- 2026-06-23: BUILT via Codex CLI (gpt-5.5). All 6 files implemented per spec + the
  `test_config.py` guardrail amendment (file 6). Verify GREEN: ruff format/check clean ·
  mypy clean (49 files) · 145 passed (139 baseline + 6 new composite tests). `git diff --stat`
  = only the spec'd files. **🟡 UNCOMMITTED — awaiting owner commit approval (paused).**
  On resume: approve commit → move spec to done/ → build `brain-sensitivity-routing` (final in batch).
