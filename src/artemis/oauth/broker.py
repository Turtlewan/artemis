"""Google OAuth broker for local loopback auth-code + PKCE flows.

Secret values are read from and written to the injected secret store only. This
module must never log, return, or include client secrets, authorization codes,
refresh tokens, access tokens, or token endpoint bodies in raised errors.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import socket
import time
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlparse

import httpx


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

DEFAULT_ACCOUNT = "default"
CLIENT_ID_SECRET_NAME = "google_oauth_client_id"
CLIENT_SECRET_SECRET_NAME = "google_oauth_client_secret"
REFRESH_SECRET_PREFIX = "google_refresh:"
GRANTED_SCOPES_PREFIX = "google_scopes:"

_HTTP_CLOSED_BODY = b"Connection closed.\n"
_MAX_REQUEST_BYTES = 8192


class SecretStore(Protocol):
    """Minimal secret-store surface used by the broker."""

    def get(self, name: str) -> str | None:
        """Return a secret by name, or None when absent."""
        ...

    def set(self, name: str, value: str) -> None:
        """Persist a secret value without disclosing it."""
        ...

    def delete(self, name: str) -> None:
        """Delete a stored secret value."""
        ...


class OAuthUnavailable(RuntimeError):
    """OAuth is unavailable; callers should ask the owner to reconnect Google."""


class ScopeNotGranted(OAuthUnavailable):
    """The connected account did not grant the requested OAuth scope."""


@dataclass(frozen=True)
class ConnectResult:
    """Safe connect result. Token material is intentionally omitted."""

    account: str
    granted_scopes: tuple[str, ...]


@dataclass(frozen=True)
class AccountStatus:
    """Safe account status. Token material is intentionally omitted."""

    connected: bool
    granted_scopes: tuple[str, ...]


@dataclass
class _PendingConnect:
    state: str
    verifier: str
    redirect_uri: str
    scopes: tuple[str, ...]
    account: str
    listener: socket.socket
    expires_at: float


@dataclass
class _AccessCacheEntry:
    token: str
    expires_at: float


def _validate_account(account: str) -> str:
    """Reject empty or email-derived account labels (identity hard-block).

    Account labels are fixed internal identifiers, never a user email — an email
    can change and must not be a primary key. Enforced structurally, not by
    convention, so oauth-2/3/4 callers cannot pass an email through.
    """

    if not account or "@" in account:
        raise OAuthUnavailable("Invalid Google OAuth account label")
    return account


def generate_state() -> str:
    """Generate a CSPRNG OAuth state value."""

    return secrets.token_urlsafe(32)


def generate_pkce() -> tuple[str, str]:
    """Return a PKCE code verifier and RFC 7636 S256 code challenge."""

    verifier = secrets.token_urlsafe(96)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_consent_url(
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    challenge: str,
    state: str,
) -> str:
    """Build Google's consent URL for an offline-access PKCE authorization flow."""

    params = {
        "access_type": "offline",
        "client_id": client_id,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "consent",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


class OAuthBroker:
    """Google OAuth broker with keychain-only refresh-token storage."""

    def __init__(
        self,
        *,
        secrets_store: SecretStore,
        http_client: httpx.AsyncClient | None = None,
        open_browser: Callable[[str], bool] = webbrowser.open,
        socket_factory: Callable[[], socket.socket] | None = None,
        loopback_timeout_s: float = 120.0,
        cache_skew_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = secrets_store
        self._http = http_client
        self._open_browser = open_browser
        self._socket_factory = socket_factory or self._default_socket
        self._loopback_timeout_s = loopback_timeout_s
        self._cache_skew_s = cache_skew_s
        self._clock = clock
        self._pending: _PendingConnect | None = None
        self._access_cache: dict[tuple[str, str], _AccessCacheEntry] = {}

    @property
    def listener_address(self) -> tuple[str, int] | None:
        """Return the current loopback listener address for tests/diagnostics."""

        if self._pending is None:
            return None
        host, port = self._pending.listener.getsockname()[:2]
        return str(host), int(port)

    def begin_connect(self, scopes: Sequence[str], *, account: str = DEFAULT_ACCOUNT) -> str:
        """Start a local Google connect flow and return the consent URL."""

        account = _validate_account(account)
        self._clear_expired_pending()
        if self._pending is not None:
            raise OAuthUnavailable("A Google OAuth connection is already pending")

        client_id = self._required_secret(CLIENT_ID_SECRET_NAME)
        verifier, challenge = generate_pkce()
        state = generate_state()
        listener = self._socket_factory()
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.setblocking(False)
            host, port = listener.getsockname()[:2]
            redirect_uri = f"http://{host}:{int(port)}/callback"
            scopes_tuple = tuple(scopes)
            self._pending = _PendingConnect(
                state=state,
                verifier=verifier,
                redirect_uri=redirect_uri,
                scopes=scopes_tuple,
                account=account,
                listener=listener,
                expires_at=self._clock() + self._loopback_timeout_s,
            )
            consent_url = build_consent_url(
                client_id,
                redirect_uri,
                scopes_tuple,
                challenge,
                state,
            )
            self._open_browser(consent_url)
            return consent_url
        except Exception:
            listener.close()
            self._pending = None
            raise

    def account_status(self, account: str = DEFAULT_ACCOUNT) -> AccountStatus:
        """Return stored Google OAuth account status without touching the network."""

        account = _validate_account(account)
        connected = self._store.get(_refresh_key(account)) is not None
        raw_scopes = self._store.get(_scopes_key(account))
        if raw_scopes is None:
            granted_scopes: tuple[str, ...] = ()
        else:
            granted_scopes = _parse_granted_scopes(raw_scopes)
        return AccountStatus(connected=connected, granted_scopes=granted_scopes)

    async def listen_for_callback(self) -> ConnectResult:
        """Serve the loopback listener until a valid callback completes or times out."""

        while True:
            pending = self._active_pending()
            timeout = max(0.0, pending.expires_at - self._clock())
            loop = asyncio.get_running_loop()
            try:
                conn, _addr = await asyncio.wait_for(loop.sock_accept(pending.listener), timeout)
            except TimeoutError:
                self._discard_pending()
                raise OAuthUnavailable("Google OAuth connection timed out") from None

            try:
                parsed = await self._read_loopback_request(conn)
                if parsed is None:
                    await self._write_loopback_response(conn, status=404)
                    continue

                code, state = parsed
                try:
                    result = await self.complete_connect(code=code, state=state)
                except OAuthUnavailable:
                    await self._write_loopback_response(conn, status=200)
                    raise
                await self._write_loopback_response(conn, status=200)
                return result
            finally:
                conn.close()

    async def complete_connect(self, *, code: str, state: str) -> ConnectResult:
        """Exchange an auth code for a refresh token and store only safe metadata."""

        pending = self._active_pending()
        self._discard_pending()
        if not hmac.compare_digest(state, pending.state):
            raise OAuthUnavailable("Google OAuth state did not match")

        client_id = self._required_secret(CLIENT_ID_SECRET_NAME)
        client_secret = self._required_secret(CLIENT_SECRET_SECRET_NAME)
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": pending.verifier,
            "grant_type": "authorization_code",
            "redirect_uri": pending.redirect_uri,
        }
        token_response = await self._post_token(payload, "Google OAuth token exchange failed")
        refresh_token = _required_str(token_response, "refresh_token")
        scope_text = _optional_str(token_response, "scope")
        granted_scopes = _scope_tuple(scope_text.split() if scope_text else pending.scopes)

        self._store.set(_refresh_key(pending.account), refresh_token)
        self._store.set(_scopes_key(pending.account), json.dumps(list(granted_scopes)))
        return ConnectResult(account=pending.account, granted_scopes=granted_scopes)

    async def mint_access_token(self, account: str, scope: str) -> str:
        """Mint or return a cached access token for an already granted scope."""

        account = _validate_account(account)
        granted_scopes = self._granted_scopes(account)
        if scope not in granted_scopes:
            raise ScopeNotGranted("Google OAuth scope was not granted")

        cache_key = (account, scope)
        cached = self._access_cache.get(cache_key)
        if cached is not None and cached.expires_at > self._clock():
            return cached.token

        refresh_token = self._store.get(_refresh_key(account))
        if refresh_token is None:
            raise OAuthUnavailable("Google OAuth refresh token is missing")

        client_id = self._required_secret(CLIENT_ID_SECRET_NAME)
        client_secret = self._required_secret(CLIENT_SECRET_SECRET_NAME)
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": scope,
        }
        token_response = await self._post_token(payload, "Google OAuth token refresh failed")
        access_token = _required_str(token_response, "access_token")
        expires_in = _required_int(token_response, "expires_in")
        rotated_refresh = _optional_str(token_response, "refresh_token")
        if rotated_refresh:
            self._store.set(_refresh_key(account), rotated_refresh)

        usable_for = max(0.0, float(expires_in) - self._cache_skew_s)
        self._access_cache[cache_key] = _AccessCacheEntry(
            token=access_token,
            expires_at=self._clock() + usable_for,
        )
        return access_token

    async def disconnect(self, account: str) -> None:
        """Best-effort revoke and delete locally stored Google OAuth credentials."""

        account = _validate_account(account)
        refresh_token = self._store.get(_refresh_key(account))
        revoke_failed = False
        if refresh_token is not None:
            payload = {"token": refresh_token}
            try:
                await self._post_revoke(payload)
            except OAuthUnavailable:
                revoke_failed = True
        self._store.delete(_refresh_key(account))
        self._store.delete(_scopes_key(account))
        for cache_key in list(self._access_cache):
            if cache_key[0] == account:
                del self._access_cache[cache_key]
        if revoke_failed:
            raise OAuthUnavailable("Google OAuth revoke failed")

    async def _post_token(self, data: dict[str, str], failure_message: str) -> dict[str, object]:
        response = await self._post_form(GOOGLE_TOKEN_URL, data, failure_message)
        return _json_object(response, failure_message)

    async def _post_revoke(self, data: dict[str, str]) -> None:
        await self._post_form(GOOGLE_REVOKE_URL, data, "Google OAuth revoke failed")

    async def _post_form(
        self,
        url: str,
        data: dict[str, str],
        failure_message: str,
    ) -> httpx.Response:
        try:
            if self._http is not None:
                response = await self._http.post(url, data=data)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, data=data)
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            raise OAuthUnavailable(failure_message) from None

    async def _read_loopback_request(self, conn: socket.socket) -> tuple[str, str] | None:
        loop = asyncio.get_running_loop()
        chunks: list[bytes] = []
        total = 0
        while b"\r\n\r\n" not in b"".join(chunks):
            chunk = await loop.sock_recv(conn, 1024)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_REQUEST_BYTES:
                return None

        try:
            request_line = b"".join(chunks).split(b"\r\n", 1)[0].decode("ascii")
        except UnicodeDecodeError:
            return None
        parts = request_line.split(" ")
        if len(parts) < 3 or parts[0] != "GET":
            return None

        parsed = urlparse(parts[1])
        if parsed.path != "/callback":
            return None
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
        # Require code + state to be present and single-valued. Google's real redirect also
        # carries extra params (scope, authuser, prompt, hd) — accept and ignore those rather
        # than rejecting the callback (an exact-set check silently drops the real Google flow).
        if "code" not in query or "state" not in query:
            return None
        codes = query["code"]
        states = query["state"]
        if len(codes) != 1 or len(states) != 1 or not codes[0] or not states[0]:
            return None
        return codes[0], states[0]

    async def _write_loopback_response(self, conn: socket.socket, *, status: int) -> None:
        reason = "OK" if status == 200 else "Not Found"
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(_HTTP_CLOSED_BODY)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii") + _HTTP_CLOSED_BODY
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(conn, response)

    def _required_secret(self, name: str) -> str:
        value = self._store.get(name)
        if value is None or value == "":
            raise OAuthUnavailable("Google OAuth client credentials are not configured")
        return value

    def _active_pending(self) -> _PendingConnect:
        pending = self._pending
        if pending is None:
            raise OAuthUnavailable("No Google OAuth connection is pending")
        if pending.expires_at <= self._clock():
            self._discard_pending()
            raise OAuthUnavailable("Google OAuth connection expired")
        return pending

    def _clear_expired_pending(self) -> None:
        if self._pending is not None and self._pending.expires_at <= self._clock():
            self._discard_pending()

    def _discard_pending(self) -> None:
        pending = self._pending
        self._pending = None
        if pending is not None:
            pending.listener.close()

    def _granted_scopes(self, account: str) -> tuple[str, ...]:
        raw = self._store.get(_scopes_key(account))
        if raw is None:
            raise OAuthUnavailable("Google OAuth granted scopes are missing")
        return _parse_granted_scopes(raw)

    @staticmethod
    def _default_socket() -> socket.socket:
        return socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def _json_object(response: httpx.Response, failure_message: str) -> dict[str, object]:
    try:
        data: Any = response.json()
    except ValueError:
        raise OAuthUnavailable(failure_message) from None
    if not isinstance(data, dict):
        raise OAuthUnavailable(failure_message)
    return data


def _required_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or value == "":
        raise OAuthUnavailable("Google OAuth token response was incomplete")
    return value


def _optional_str(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise OAuthUnavailable("Google OAuth token response was invalid")
    return value


def _required_int(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or value < 0:
        raise OAuthUnavailable("Google OAuth token response was incomplete")
    return value


def _scope_tuple(scopes: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(scopes)))


def _parse_granted_scopes(raw: str) -> tuple[str, ...]:
    try:
        loaded: Any = json.loads(raw)
    except json.JSONDecodeError:
        raise OAuthUnavailable("Google OAuth granted scopes are invalid") from None
    if not isinstance(loaded, list) or not all(isinstance(scope, str) for scope in loaded):
        raise OAuthUnavailable("Google OAuth granted scopes are invalid")
    return _scope_tuple(loaded)


def _refresh_key(account: str) -> str:
    return f"{REFRESH_SECRET_PREFIX}{account}"


def _scopes_key(account: str) -> str:
    return f"{GRANTED_SCOPES_PREFIX}{account}"
