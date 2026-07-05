from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from artemis.oauth.broker import (
    CLIENT_ID_SECRET_NAME,
    CLIENT_SECRET_SECRET_NAME,
    DEFAULT_ACCOUNT,
    GOOGLE_REVOKE_URL,
    OAuthBroker,
    OAuthUnavailable,
    ScopeNotGranted,
    build_consent_url,
    generate_pkce,
    generate_state,
)


class FakeSecretStore:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values = dict(initial or {})
        self.writes: list[tuple[str, str]] = []

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value
        self.writes.append((name, value))

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class MutableClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _store() -> FakeSecretStore:
    return FakeSecretStore(
        {
            CLIENT_ID_SECRET_NAME: "client-id",
            CLIENT_SECRET_SECRET_NAME: "client-secret",
        }
    )


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def _single(query: dict[str, list[str]], key: str) -> str:
    values = query[key]
    assert len(values) == 1
    return values[0]


def _form(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode())


def test_generate_pkce_and_consent_url_are_rfc7636_s256() -> None:
    verifier, challenge = generate_pkce()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert challenge == expected
    assert "=" not in challenge

    state = generate_state()
    url = build_consent_url(
        "client-id",
        "http://127.0.0.1:54321/callback",
        ["scope-a", "scope-b"],
        challenge,
        state,
    )
    query = _query(url)
    assert _single(query, "access_type") == "offline"
    assert _single(query, "prompt") == "consent"
    assert _single(query, "code_challenge_method") == "S256"
    assert _single(query, "code_challenge") == challenge
    assert _single(query, "scope") == "scope-a scope-b"
    assert _single(query, "state") == state
    assert generate_state() != generate_state()


def test_account_status_reads_store_without_returning_tokens() -> None:
    store = _store()
    store.set("google_refresh:default", "refresh-token-secret")
    store.set("google_scopes:default", json.dumps(["scope-b", "scope-a", "scope-a"]))
    broker = OAuthBroker(secrets_store=store, open_browser=lambda _url: True)

    connected = broker.account_status()
    unknown = broker.account_status("other")

    assert connected.connected is True
    assert connected.granted_scopes == ("scope-a", "scope-b")
    assert unknown.connected is False
    assert unknown.granted_scopes == ()
    assert "refresh-token-secret" not in repr(connected)
    assert "refresh-token-secret" not in repr(unknown)


@pytest.mark.asyncio
async def test_complete_connect_stores_refresh_and_scopes_without_returning_tokens() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "refresh_token": "refresh-token",
                "scope": "scope-a scope-b",
                "access_token": "access-token",
                "expires_in": 3600,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = _store()
        browser_urls: list[str] = []

        def open_browser(url: str) -> bool:
            browser_urls.append(url)
            return True

        broker = OAuthBroker(
            secrets_store=store,
            http_client=client,
            open_browser=open_browser,
        )

        consent_url = broker.begin_connect(["scope-a", "scope-b"])
        query = _query(consent_url)
        result = await broker.complete_connect(
            code="auth-code",
            state=_single(query, "state"),
        )

    assert browser_urls == [consent_url]
    assert result.account == DEFAULT_ACCOUNT
    assert result.granted_scopes == ("scope-a", "scope-b")
    assert not hasattr(result, "access_token")
    assert not hasattr(result, "refresh_token")
    assert store.values["google_refresh:default"] == "refresh-token"
    assert json.loads(store.values["google_scopes:default"]) == ["scope-a", "scope-b"]
    assert _single(_form(requests[0]), "redirect_uri") == _single(query, "redirect_uri")


@pytest.mark.asyncio
async def test_state_mismatch_uses_constant_time_compare_and_stores_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compared: list[tuple[str, str]] = []
    original: Callable[[str, str], bool] = hmac.compare_digest

    def spy_compare(left: str, right: str) -> bool:
        compared.append((left, right))
        return original(left, right)

    monkeypatch.setattr(hmac, "compare_digest", spy_compare)
    store = _store()
    broker = OAuthBroker(secrets_store=store, open_browser=lambda _url: True)
    broker.begin_connect(["scope-a"])

    with pytest.raises(OAuthUnavailable):
        await broker.complete_connect(code="auth-code", state="bad-state")

    assert compared
    assert "google_refresh:default" not in store.values
    assert "google_scopes:default" not in store.values


@pytest.mark.asyncio
async def test_replayed_code_and_state_succeeds_at_most_once() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"refresh_token": "refresh-token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        broker = OAuthBroker(
            secrets_store=_store(),
            http_client=client,
            open_browser=lambda _url: True,
        )
        consent_url = broker.begin_connect(["scope-a"])
        state = _single(_query(consent_url), "state")
        await broker.complete_connect(code="auth-code", state=state)
        with pytest.raises(OAuthUnavailable):
            await broker.complete_connect(code="auth-code", state=state)

    assert calls == 1


@pytest.mark.asyncio
async def test_loopback_binds_localhost_rejects_non_callback_and_completes() -> None:
    token_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(200, json={"refresh_token": "refresh-token", "scope": "scope-a"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        broker = OAuthBroker(
            secrets_store=_store(),
            http_client=client,
            open_browser=lambda _url: True,
        )
        consent_url = broker.begin_connect(["scope-a"])
        query = _query(consent_url)
        address = broker.listener_address
        assert address is not None
        assert address[0] == "127.0.0.1"

        callback_task = asyncio.create_task(broker.listen_for_callback())
        closed = await _send_loopback(address, "/not-callback")
        assert b"Connection closed." in closed
        assert broker.listener_address == address

        valid = f"/callback?code=auth-code&state={_single(query, 'state')}"
        ok = await _send_loopback(address, valid)
        result = await callback_task

    assert b"Google connected" in ok
    assert result.account == DEFAULT_ACCOUNT
    assert _single(_form(token_requests[0]), "redirect_uri") == _single(query, "redirect_uri")


@pytest.mark.asyncio
async def test_loopback_malformed_request_does_not_touch_pending_state() -> None:
    broker = OAuthBroker(secrets_store=_store(), open_browser=lambda _url: True)
    broker.begin_connect(["scope-a"])
    address = broker.listener_address
    assert address is not None

    callback_task = asyncio.create_task(broker.listen_for_callback())
    # Genuinely malformed: missing the state param -> rejected, pending untouched.
    await _send_loopback(address, "/callback?code=auth-code")
    assert broker.listener_address == address
    callback_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await callback_task


@pytest.mark.asyncio
async def test_loopback_accepts_google_extra_params() -> None:
    """Google's real redirect carries extra params (scope/authuser/prompt) — accept it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "refresh-token", "scope": "scope-a"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        broker = OAuthBroker(
            secrets_store=_store(),
            http_client=client,
            open_browser=lambda _url: True,
        )
        consent_url = broker.begin_connect(["scope-a"])
        state = _single(_query(consent_url), "state")
        address = broker.listener_address
        assert address is not None

        callback_task = asyncio.create_task(broker.listen_for_callback())
        google_style = (
            f"/callback?state={state}&code=auth-code"
            "&scope=https://www.googleapis.com/auth/calendar.readonly"
            "&authuser=0&prompt=consent"
        )
        ok = await _send_loopback(address, google_style)
        result = await callback_task

    assert b"Google connected" in ok
    assert result.account == DEFAULT_ACCOUNT
    assert result.granted_scopes == ("scope-a",)


@pytest.mark.asyncio
async def test_loopback_failed_exchange_gets_distinct_failure_body() -> None:
    """Success and failure must not be indistinguishable in the owner's browser tab."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        broker = OAuthBroker(
            secrets_store=_store(),
            http_client=client,
            open_browser=lambda _url: True,
        )
        consent_url = broker.begin_connect(["scope-a"])
        state = _single(_query(consent_url), "state")
        address = broker.listener_address
        assert address is not None

        callback_task = asyncio.create_task(broker.listen_for_callback())
        body = await _send_loopback(address, f"/callback?code=auth-code&state={state}")
        with pytest.raises(OAuthUnavailable):
            await callback_task

    assert b"Google connect FAILED" in body
    assert b"Google connected." not in body


@pytest.mark.asyncio
async def test_loopback_timeout_expires_pending_state() -> None:
    broker = OAuthBroker(
        secrets_store=_store(),
        open_browser=lambda _url: True,
        loopback_timeout_s=0.01,
    )
    broker.begin_connect(["scope-a"])
    with pytest.raises(OAuthUnavailable):
        await broker.listen_for_callback()
    assert broker.listener_address is None


@pytest.mark.asyncio
async def test_mint_access_token_uses_cache_then_refreshes_after_skew() -> None:
    clock = MutableClock()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"access_token": f"access-{calls}", "expires_in": 120})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = _store()
        store.set("google_refresh:default", "refresh-token")
        store.set("google_scopes:default", json.dumps(["scope-a"]))
        broker = OAuthBroker(
            secrets_store=store,
            http_client=client,
            open_browser=lambda _url: True,
            clock=clock,
            cache_skew_s=60,
        )

        assert await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a") == "access-1"
        assert await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a") == "access-1"
        clock.now += 61
        assert await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a") == "access-2"

    assert calls == 2
    assert all("access" not in name for name in store.values)


@pytest.mark.asyncio
async def test_mint_access_token_accepts_joined_scope_set_and_posts_joined_scope() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"access_token": "access-token", "expires_in": 120})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = _store()
        store.set("google_refresh:default", "refresh-token")
        store.set("google_scopes:default", json.dumps(["scope-a", "scope-b"]))
        broker = OAuthBroker(
            secrets_store=store,
            http_client=client,
            open_browser=lambda _url: True,
        )

        assert await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a scope-b") == "access-token"
        assert await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a scope-b") == "access-token"

    assert len(requests) == 1
    assert _single(_form(requests[0]), "scope") == "scope-a scope-b"


@pytest.mark.asyncio
async def test_mint_access_token_joined_scope_set_rejects_any_ungranted_scope() -> None:
    store = _store()
    store.set("google_refresh:default", "refresh-token")
    store.set("google_scopes:default", json.dumps(["scope-a"]))
    broker = OAuthBroker(secrets_store=store, open_browser=lambda _url: True)

    with pytest.raises(ScopeNotGranted):
        await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a scope-b")


@pytest.mark.asyncio
async def test_mint_access_token_single_scope_posts_single_scope_string() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"access_token": "access-token", "expires_in": 120})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = _store()
        store.set("google_refresh:default", "refresh-token")
        store.set("google_scopes:default", json.dumps(["scope-a"]))
        broker = OAuthBroker(
            secrets_store=store,
            http_client=client,
            open_browser=lambda _url: True,
        )

        assert await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a") == "access-token"

    assert len(requests) == 1
    assert _single(_form(requests[0]), "scope") == "scope-a"


@pytest.mark.asyncio
async def test_refresh_token_rotation_overwrites_keychain_entry() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access-token",
                "expires_in": 3600,
                "refresh_token": "rotated-refresh",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = _store()
        store.set("google_refresh:default", "old-refresh")
        store.set("google_scopes:default", json.dumps(["scope-a"]))
        broker = OAuthBroker(
            secrets_store=store,
            http_client=client,
            open_browser=lambda _url: True,
        )
        await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a")

    assert store.values["google_refresh:default"] == "rotated-refresh"


@pytest.mark.asyncio
async def test_missing_refresh_token_fails_closed_and_ungranted_scope_raises() -> None:
    store = _store()
    store.set("google_scopes:default", json.dumps(["scope-a"]))
    broker = OAuthBroker(secrets_store=store, open_browser=lambda _url: True)

    with pytest.raises(OAuthUnavailable):
        await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a")
    with pytest.raises(ScopeNotGranted):
        await broker.mint_access_token(DEFAULT_ACCOUNT, "scope-b")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "secret_fragments"),
    [
        ("state", ["client-secret", "auth-code", "refresh-token", "access-token", "body-secret"]),
        (
            "exchange",
            ["client-secret", "auth-code", "refresh-token", "access-token", "body-secret"],
        ),
        ("refresh", ["client-secret", "auth-code", "refresh-token", "access-token", "body-secret"]),
        (
            "disconnect",
            ["client-secret", "auth-code", "refresh-token", "access-token", "body-secret"],
        ),
    ],
)
async def test_errors_are_sanitized(operation: str, secret_fragments: list[str]) -> None:
    store = _store()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="body-secret refresh-token access-token client-secret")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        broker = OAuthBroker(
            secrets_store=store,
            http_client=client,
            open_browser=lambda _url: True,
        )
        if operation == "state":
            broker.begin_connect(["scope-a"])
            raised = await _raises_oauth(
                lambda: broker.complete_connect(code="auth-code", state="bad")
            )
        elif operation == "exchange":
            url = broker.begin_connect(["scope-a"])
            raised = await _raises_oauth(
                lambda: broker.complete_connect(
                    code="auth-code", state=_single(_query(url), "state")
                )
            )
        elif operation == "refresh":
            store.set("google_refresh:default", "refresh-token")
            store.set("google_scopes:default", json.dumps(["scope-a"]))
            raised = await _raises_oauth(
                lambda: broker.mint_access_token(DEFAULT_ACCOUNT, "scope-a")
            )
        else:
            store.set("google_refresh:default", "refresh-token")
            raised = await _raises_oauth(lambda: broker.disconnect(DEFAULT_ACCOUNT))

    message = f"{raised!r} {raised}"
    for fragment in secret_fragments:
        assert fragment not in message


@pytest.mark.asyncio
async def test_disconnect_revokes_and_deletes_stored_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = _store()
        store.set("google_refresh:default", "refresh-token")
        store.set("google_scopes:default", json.dumps(["scope-a"]))
        broker = OAuthBroker(
            secrets_store=store,
            http_client=client,
            open_browser=lambda _url: True,
        )
        await broker.disconnect(DEFAULT_ACCOUNT)

    assert requests[0].url == httpx.URL(GOOGLE_REVOKE_URL)
    assert "google_refresh:default" not in store.values
    assert "google_scopes:default" not in store.values


async def _send_loopback(address: tuple[str, int], target: str) -> bytes:
    reader, writer = await asyncio.open_connection(*address)
    writer.write(f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode("ascii"))
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


async def _raises_oauth(call: Callable[[], Any]) -> OAuthUnavailable:
    with pytest.raises(OAuthUnavailable) as exc_info:
        result = call()
        if hasattr(result, "__await__"):
            await result
    return exc_info.value


@pytest.mark.asyncio
async def test_email_derived_account_labels_are_rejected() -> None:
    broker = OAuthBroker(secrets_store=_store(), open_browser=lambda _url: True)

    with pytest.raises(OAuthUnavailable):
        broker.begin_connect(["scope-a"], account="owner@example.com")
    with pytest.raises(OAuthUnavailable):
        await broker.mint_access_token("owner@example.com", "scope-a")
    with pytest.raises(OAuthUnavailable):
        await broker.disconnect("owner@example.com")
    with pytest.raises(OAuthUnavailable):
        broker.begin_connect(["scope-a"], account="")
