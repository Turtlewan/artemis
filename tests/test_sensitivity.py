"""Tests for the local sensitivity classifier gate."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import cast

import pytest

from artemis.config import ModelRole, Settings
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector
from artemis.sensitivity import CLASSIFIER_ROLE, SensitivityClassifier


class FakeSettings:
    """Lightweight settings double exposing the roles map used by the classifier."""

    def __init__(self, roles: dict[str, ModelRole]) -> None:
        self.roles = roles


class FakeModelPort:
    """Fake ModelPort for classifier tests."""

    def __init__(self, text: str = '{"label":"general"}', raises: bool = False) -> None:
        self.text = text
        self.raises = raises
        self.call_count = 0
        self.last_role: str | None = None
        self.last_messages: Sequence[Message] = []
        self.last_response_schema: dict[str, object] | None = None

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.call_count += 1
        self.last_role = role
        self.last_messages = messages
        self.last_response_schema = response_schema
        if self.raises:
            raise RuntimeError("hidden account password")
        return ModelResponse(
            text=self.text,
            finish_reason="stop",
            usage=Usage(1, 1, 2),
            origin="local",
            model_id="fake",
        )

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        async def _gen() -> AsyncIterator[str]:
            yield ""

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[0.0] for _ in texts]


def _settings(endpoint: str) -> Settings:
    role = ModelRole(endpoint=endpoint, model_id="m", adapter="openai")
    return cast(Settings, FakeSettings({CLASSIFIER_ROLE: role}))


def _empty_settings() -> Settings:
    return cast(Settings, FakeSettings({}))


@pytest.mark.asyncio
async def test_classifier_returns_general_on_loopback_general() -> None:
    model = FakeModelPort(text='{"label":"general"}')
    classifier = SensitivityClassifier(model, _settings("http://127.0.0.1:8040/v1"))

    assert await classifier.classify("what is the capital of France?") == "general"
    assert model.call_count == 1
    assert model.last_role == CLASSIFIER_ROLE
    assert model.last_response_schema is not None
    assert any("<user_request>" in message.content for message in model.last_messages)


@pytest.mark.asyncio
async def test_classifier_returns_sensitive_on_loopback_sensitive() -> None:
    model = FakeModelPort(text='{"label":"sensitive"}')
    classifier = SensitivityClassifier(model, _settings("http://localhost:8040/v1"))

    assert await classifier.classify("summarize my bank statement") == "sensitive"


@pytest.mark.asyncio
async def test_classifier_raises_fail_closed_without_logging_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_text = "my private account balance is 123"
    model = FakeModelPort(raises=True)
    classifier = SensitivityClassifier(model, _settings("http://127.0.0.1:8040/v1"))

    assert await classifier.classify(request_text) == "sensitive"
    assert "RuntimeError" in caplog.text
    assert request_text not in caplog.text
    assert "hidden account password" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "The request seems general.",
        "[]",
        '{"label":"banana"}',
    ],
)
async def test_classifier_unparseable_or_unknown_output_fails_closed(text: str) -> None:
    model = FakeModelPort(text=text)
    classifier = SensitivityClassifier(model, _settings("http://[::1]:8040/v1"))

    assert await classifier.classify("tell me a joke") == "sensitive"


@pytest.mark.asyncio
async def test_classifier_non_loopback_endpoint_fails_closed_without_model_call() -> None:
    model = FakeModelPort(text='{"label":"general"}')
    classifier = SensitivityClassifier(model, _settings("http://evil.example.com/v1"))

    assert await classifier.classify("tell me a joke") == "sensitive"
    assert model.call_count == 0


@pytest.mark.asyncio
async def test_classifier_missing_role_fails_closed_without_model_call() -> None:
    model = FakeModelPort(text='{"label":"general"}')
    classifier = SensitivityClassifier(model, _empty_settings())

    assert await classifier.classify("tell me a joke") == "sensitive"
    assert model.call_count == 0
