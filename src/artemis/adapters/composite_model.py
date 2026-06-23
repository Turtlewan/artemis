"""CompositeModelPort - dispatch by role adapter with Codex fallback."""

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
        self._fallback_role = self._settings.codex_fallback_role

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
                    role=role,
                    messages=messages,
                    response_schema=response_schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception:
                # DEGRADED: content-free log (no exc_info - the exception body could carry
                # context; the adapter already scrubs its message). Visibly marks the
                # degraded-to-local path so an auth/outage failure is observable.
                # [apex-security BLOCK + FLAG]
                logger.warning(
                    "DEGRADED: Codex unavailable for role %s - serving from local fallback %s",
                    role,
                    self._fallback_role,
                )
                return await self._local.complete(
                    role=self._fallback_role,
                    messages=messages,
                    response_schema=response_schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
        return await self._local.complete(
            role=role,
            messages=messages,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def complete_stream(
        self, *, role: str, messages: Sequence[Message], temperature: float = 0.7
    ) -> AsyncIterator[str]:
        async def _stream() -> AsyncIterator[str]:
            # Codex roles: route through complete() (single-shot + built-in fallback) and
            # yield once. This avoids a split stream - Codex has no real token stream, and a
            # mid-generator try/except fallback could interleave two sources if Codex ever
            # raised after the first chunk. [apex-python BLOCK]
            if self._is_codex_role(role):
                resp = await self.complete(role=role, messages=messages, temperature=temperature)
                yield resp.text
                return
            async for chunk in self._local.complete_stream(
                role=role, messages=messages, temperature=temperature
            ):
                yield chunk

        return _stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return await self._local.embed(role, texts)
