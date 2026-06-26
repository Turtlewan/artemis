"""Pluggable per-task coder backend selection.

The router returns LiteLLM/OpenAI-compatible configuration only; it does not
call LiteLLM or any model. Coding is intentionally treated as non-sensitive for
ADR-031 D, so cloud coder backends are allowed here. API keys are carried as
environment variable names, never read or logged as secret values.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from artemis.runtime_config import CoderBackendConfig, RuntimeConfig, get_runtime_config


class CoderBackend(BaseModel):
    """Selected LiteLLM backend configuration for a coder task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    base_url: str | None
    api_key_env: str
    tier: Literal["cheap", "standard"]


class CoderRouter:
    """Select configured coder backends by task class."""

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self._config = config or get_runtime_config()

    def select(self, task_class: str) -> CoderBackend:
        """Return the configured backend for ``task_class``, or the default."""
        routing = self._config.coder_routing
        backend = routing.task_backends.get(task_class)
        if backend is None:
            backend = routing.task_backends[routing.default_task_class]
        return self._from_config(backend)

    @staticmethod
    def _from_config(config: CoderBackendConfig) -> CoderBackend:
        return CoderBackend(
            model=config.model,
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            tier=config.tier,
        )
