"""Tests for session-gated secret CRUD routes."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.types import Message, ModelResponse, Usage


class FakeSecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)

    def list_names(self) -> list[str]:
        return sorted(self._values)


class FakeModel:
    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = messages, response_schema, temperature, max_tokens
        return ModelResponse(
            text="",
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def _client(tmp_path: Path, store: FakeSecretStore) -> TestClient:
    app = create_app(data_dir=tmp_path, model=FakeModel(), secrets=store)
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    return TestClient(app)


def test_set_list_and_delete_secret_without_echoing_value(tmp_path: Path) -> None:
    store = FakeSecretStore()
    client = _client(tmp_path, store)
    secret_value = "sk-test-secret-value"

    set_response = client.post(
        "/app/secrets",
        json={"name": "OPENAI_API_KEY", "value": secret_value},
    )

    assert set_response.status_code == 204
    assert set_response.content == b""
    assert store.get("OPENAI_API_KEY") == secret_value

    list_response = client.get("/app/secrets")

    assert list_response.status_code == 200
    assert list_response.json() == {"names": ["OPENAI_API_KEY"]}
    assert secret_value not in list_response.text

    delete_response = client.delete("/app/secrets/OPENAI_API_KEY")

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert store.get("OPENAI_API_KEY") is None
    assert client.get("/app/secrets").json() == {"names": []}


def test_secret_routes_require_session(tmp_path: Path) -> None:
    client = TestClient(create_app(data_dir=tmp_path, model=FakeModel(), secrets=FakeSecretStore()))

    assert (
        client.post(
            "/app/secrets",
            json={"name": "OPENAI_API_KEY", "value": "sk-test-secret-value"},
        ).status_code
        == 401
    )
    assert client.get("/app/secrets").status_code == 401
    assert client.delete("/app/secrets/OPENAI_API_KEY").status_code == 401


def test_set_secret_rejects_url_unsafe_name(tmp_path: Path) -> None:
    """Names with URL-significant chars are rejected (422) so the DELETE {name} URL stays safe."""
    store = FakeSecretStore()
    client = _client(tmp_path, store)
    for bad in ["api?v=2", "site/key", "with#frag", "per%cent", "has space"]:
        resp = client.post("/app/secrets", json={"name": bad, "value": "v"})
        assert resp.status_code == 422, bad
    assert store.list_names() == []  # nothing stored
    # a normal env-var-style name is accepted
    assert (
        client.post("/app/secrets", json={"name": "GITHUB_TOKEN", "value": "v"}).status_code == 204
    )
