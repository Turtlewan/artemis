"""Tests for session-gated Google OAuth routes."""

from __future__ import annotations

from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.oauth.broker import AccountStatus, DEFAULT_ACCOUNT, OAuthUnavailable
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


class StubOAuthBroker:
    def __init__(
        self,
        *,
        consent_url: str = "https://accounts.example/consent",
        configured: bool = True,
        status: AccountStatus | None = None,
    ) -> None:
        self.consent_url = consent_url
        self.configured = configured
        self.status = status or AccountStatus(
            connected=True,
            granted_scopes=("calendar.read", "mail.read"),
        )
        self.opened_urls: list[str] = []
        self.begin_scopes: tuple[str, ...] | None = None
        self.listen_calls = 0
        self.disconnect_accounts: list[str] = []

    def begin_connect(self, scopes: Sequence[str], *, account: str = DEFAULT_ACCOUNT) -> str:
        _ = account
        if not self.configured:
            raise OAuthUnavailable("Google OAuth client credentials are not configured")
        self.begin_scopes = tuple(scopes)
        return self.consent_url

    def listen_for_callback(self) -> Coroutine[Any, Any, None]:
        self.listen_calls += 1

        async def run() -> None:
            return None

        return run()

    def account_status(self, account: str = DEFAULT_ACCOUNT) -> AccountStatus:
        _ = account
        return self.status

    async def disconnect(self, account: str) -> None:
        self.disconnect_accounts.append(account)


def _client(tmp_path: Path, broker: StubOAuthBroker) -> tuple[TestClient, FastAPI]:
    app = create_app(data_dir=tmp_path, model=FakeModel(), secrets=FakeSecretStore())
    app.state.oauth_broker = broker
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev",
        person_id="owner",
    )
    return TestClient(app), app


def test_oauth_routes_require_session(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel(), secrets=FakeSecretStore())
    app.state.oauth_broker = StubOAuthBroker()
    client = TestClient(app)

    assert (
        client.post("/app/oauth/google/connect", json={"scopes": ["calendar.read"]}).status_code
        == 401
    )
    assert client.get("/app/oauth/google/status").status_code == 401
    assert (
        client.post("/app/oauth/google/disconnect", json={"account": DEFAULT_ACCOUNT}).status_code
        == 401
    )


def test_connect_returns_consent_url_without_opening_browser_and_schedules_listener(
    tmp_path: Path,
) -> None:
    broker = StubOAuthBroker()
    client, app = _client(tmp_path, broker)

    response = client.post(
        "/app/oauth/google/connect",
        json={"scopes": ["calendar.read", "mail.read"]},
    )

    assert response.status_code == 200
    assert response.json() == {"consent_url": broker.consent_url}
    assert broker.begin_scopes == ("calendar.read", "mail.read")
    assert broker.opened_urls == []
    assert broker.listen_calls == 1
    assert app.state.oauth_connect_task is not None


def test_connect_maps_missing_client_credentials_to_typed_status(tmp_path: Path) -> None:
    broker = StubOAuthBroker(configured=False)
    client, app = _client(tmp_path, broker)

    response = client.post("/app/oauth/google/connect", json={"scopes": ["calendar.read"]})

    assert response.status_code == 200
    assert response.json() == {"status": "client_not_configured"}
    assert broker.listen_calls == 0
    assert app.state.oauth_connect_task is None


def test_status_returns_account_and_scopes_without_token_values(tmp_path: Path) -> None:
    secret_value = "refresh-token-secret"
    broker = StubOAuthBroker(
        status=AccountStatus(
            connected=True,
            granted_scopes=("calendar.read", "mail.read"),
        )
    )
    client, _app = _client(tmp_path, broker)

    response = client.get("/app/oauth/google/status")

    assert response.status_code == 200
    assert response.json() == {
        "account": DEFAULT_ACCOUNT,
        "connected": True,
        "granted_scopes": ["calendar.read", "mail.read"],
        "connect_pending": False,
        "last_connect_error": None,
    }
    assert secret_value not in response.text
    assert "token" not in response.text


def test_status_surfaces_pending_connect(tmp_path: Path) -> None:
    broker = StubOAuthBroker(status=AccountStatus(connected=False, granted_scopes=()))
    client, app = _client(tmp_path, broker)

    class NotDoneTask:
        def done(self) -> bool:
            return False

    app.state.oauth_connect_task = NotDoneTask()

    body = client.get("/app/oauth/google/status").json()

    assert body["connect_pending"] is True
    assert body["connected"] is False


def test_status_surfaces_last_connect_error(tmp_path: Path) -> None:
    broker = StubOAuthBroker(status=AccountStatus(connected=False, granted_scopes=()))
    client, app = _client(tmp_path, broker)
    app.state.oauth_last_connect_error = "Google OAuth token exchange failed"

    body = client.get("/app/oauth/google/status").json()

    assert body["last_connect_error"] == "Google OAuth token exchange failed"
    assert body["connect_pending"] is False


def test_connect_resets_previous_connect_error(tmp_path: Path) -> None:
    broker = StubOAuthBroker()
    client, app = _client(tmp_path, broker)
    app.state.oauth_last_connect_error = "Google OAuth token exchange failed"

    response = client.post("/app/oauth/google/connect", json={"scopes": ["calendar.read"]})

    assert response.status_code == 200
    assert app.state.oauth_last_connect_error is None


@pytest.mark.asyncio
async def test_listen_and_record_records_safe_failure_message(tmp_path: Path) -> None:
    from artemis.api.oauth_routes import _listen_and_record

    class FailingBroker:
        async def _fail(self) -> None:
            raise OAuthUnavailable("Google OAuth token exchange failed")

        def listen_for_callback(self) -> Coroutine[Any, Any, None]:
            return self._fail()

    class State:
        oauth_last_connect_error: str | None = None

    state = State()
    await _listen_and_record(FailingBroker(), state)  # type: ignore[arg-type]

    assert state.oauth_last_connect_error == "Google OAuth token exchange failed"


def test_disconnect_calls_broker_and_returns_success(tmp_path: Path) -> None:
    broker = StubOAuthBroker()
    client, _app = _client(tmp_path, broker)

    response = client.post("/app/oauth/google/disconnect", json={"account": "work"})

    assert response.status_code == 200
    assert response.json() == {"disconnected": True}
    assert broker.disconnect_accounts == ["work"]


def test_create_app_wires_oauth_broker(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel(), secrets=FakeSecretStore())

    assert app.state.oauth_broker is not None
    assert app.state.oauth_connect_task is None
