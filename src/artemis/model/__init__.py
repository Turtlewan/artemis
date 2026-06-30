"""Concrete model providers and clients."""

from artemis.model.anthropic_provider import AnthropicAPIProvider
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient, ModelOutputError
from artemis.model.compose import build_model_router
from artemis.model.codex_provider import CodexProvider
from artemis.model.errors import (
    AllBackendsExhaustedError,
    ProviderUnavailableError,
    QuotaExhaustedError,
)
from artemis.model.ollama_provider import OllamaProvider
from artemis.model.router import QuotaAwareRouter

__all__ = [
    "AllBackendsExhaustedError",
    "AnthropicAPIProvider",
    "ClaudeCodeProvider",
    "CodexProvider",
    "ModelClient",
    "ModelOutputError",
    "OllamaProvider",
    "ProviderUnavailableError",
    "QuotaAwareRouter",
    "QuotaExhaustedError",
    "build_model_router",
]
