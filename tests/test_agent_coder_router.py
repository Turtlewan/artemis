from __future__ import annotations

import pytest

from artemis.agentic.coder.router import CoderRouter
from artemis.runtime_config import CoderBackendConfig, CoderRoutingConfig, RuntimeConfig


def test_select_returns_configured_backend_for_task_class() -> None:
    config = RuntimeConfig(
        coder_routing=CoderRoutingConfig(
            default_task_class="standard",
            task_backends={
                "cheap": CoderBackendConfig(
                    model="deepseek/deepseek-chat",
                    base_url="https://api.deepseek.com",
                    api_key_env="DEEPSEEK_API_KEY",
                    tier="cheap",
                ),
                "standard": CoderBackendConfig(
                    model="openai/gpt-4.1-mini",
                    base_url=None,
                    api_key_env="OPENAI_API_KEY",
                    tier="standard",
                ),
            },
        ),
    )

    backend = CoderRouter(config).select("cheap")

    assert backend.model == "deepseek/deepseek-chat"
    assert backend.base_url == "https://api.deepseek.com"
    assert backend.api_key_env == "DEEPSEEK_API_KEY"
    assert backend.tier == "cheap"


def test_select_unknown_task_class_falls_back_to_default_backend() -> None:
    backend = CoderRouter(RuntimeConfig()).select("unknown-task-class")
    default_backend = RuntimeConfig().coder_routing.task_backends[
        RuntimeConfig().coder_routing.default_task_class
    ]

    assert backend.model == default_backend.model
    assert backend.base_url == default_backend.base_url
    assert backend.api_key_env == default_backend.api_key_env
    assert backend.tier == default_backend.tier


def test_backend_carries_api_key_env_name_not_literal_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_value = "runtime-secret-sentinel"
    monkeypatch.setenv("OPENAI_API_KEY", env_value)

    backend = CoderRouter(RuntimeConfig()).select("standard")
    dumped = backend.model_dump()

    assert backend.api_key_env == "OPENAI_API_KEY"
    assert env_value not in str(dumped)
    assert RuntimeConfig().coder_routing.task_backends["standard"].api_key_env == "OPENAI_API_KEY"
