"""Composition helpers for model backend routing."""

from __future__ import annotations

from artemis.model.anthropic_provider import AnthropicAPIProvider
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.model.codex_provider import CodexProvider
from artemis.model.ollama_provider import OllamaProvider
from artemis.model.router import QuotaAwareRouter
from artemis.ports.model import ModelPort


def build_model_router(
    *,
    anthropic_api_key: str | None = None,
    enable_ollama: bool = True,
) -> QuotaAwareRouter:
    """Assemble the subscription-first chain: codex -> claude-code -> anthropic-api -> ollama."""
    backends: list[tuple[str, ModelPort]] = [
        ("codex", ModelClient(CodexProvider(), model_default="gpt-5.5")),
        ("claude_code", ModelClient(ClaudeCodeProvider(), model_default="sonnet")),
        (
            "anthropic_api",
            ModelClient(
                AnthropicAPIProvider(api_key=anthropic_api_key),
                model_default="claude-sonnet-4-6",
            ),
        ),
    ]
    if enable_ollama:
        backends.append(("ollama", ModelClient(OllamaProvider(), model_default="qwen3:4b")))
    return QuotaAwareRouter(backends)
