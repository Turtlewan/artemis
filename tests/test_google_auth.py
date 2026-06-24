from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from google.auth.exceptions import RefreshError
from google.auth.transport import Response

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError
from artemis.integrations.google import cli
from artemis.integrations.google.credentials import GoogleCredentialsFactory, ReauthRequiredError
from artemis.integrations.google.oauth import (
    ConsentFailedError,
    CredentialsLike,
    GoogleOAuthConfig,
    InstalledAppFlowLike,
    MissingOAuthConfigError,
    installed_app_client_config,
    load_oauth_config,
    run_installed_app_consent,
)
from artemis.integrations.google.scopes import (
    clear_registry,
    register_google_scopes,
    required_scopes,
)
from artemis.integrations.google.tokens import InMemoryTokenStore, SqlCipherTokenStore, StoredToken


@pytest.fixture(autouse=True)
def _clear_google_scope_registry() -> Iterator[None]:
    clear_registry()
    yield
    clear_registry()


def test_scope_registry_union_validation_and_clear() -> None:
    register_google_scopes("cal", {"https://www.googleapis.com/auth/calendar.events"})
    register_google_scopes("gmail", {"https://www.googleapis.com/auth/gmail.readonly"})

    assert required_scopes() == frozenset(
        {
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/gmail.readonly",
        }
    )
    with pytest.raises(ValueError):
        register_google_scopes("bad", {""})

    clear_registry()
    assert required_scopes() == frozenset()


def test_in_memory_store_round_trips_and_repr_redacts_refresh_token() -> None:
    token = _stored_token(refresh_token="topsecret")
    store = InMemoryTokenStore()

    store.save(token)

    assert store.load() == token
    assert "topsecret" not in repr(token)
    assert "topsecret" not in str(token)
    store.clear()
    assert store.load() is None


def test_sqlcipher_token_store_locked_scope_propagates(tmp_path: Path) -> None:
    store = SqlCipherTokenStore(
        _settings(tmp_path),
        FakeKeyProvider(owner_unlocked=False),
    )

    with pytest.raises(ScopeLockedError):
        store.save(_stored_token())
    with pytest.raises(ScopeLockedError):
        store.load()


def test_consent_flow_uses_required_params_and_returns_stored_token() -> None:
    seen: dict[str, object] = {}

    def flow_factory(
        client_config: Mapping[str, object],
        scopes: Sequence[str],
    ) -> InstalledAppFlowLike:
        seen["client_config"] = client_config
        seen["scopes"] = tuple(scopes)
        return FakeFlow(FakeConsentCredentials(refresh_token="rt", scopes=["s"]), seen)

    cfg = GoogleOAuthConfig(client_id="cid", client_secret="secret")

    token = run_installed_app_consent(
        ["s"],
        cfg,
        flow_factory=flow_factory,
        open_browser=False,
    )

    assert token.refresh_token == "rt"
    assert token.scopes == ("s",)
    assert seen["scopes"] == ("s",)
    assert seen["access_type"] == "offline"
    assert seen["prompt"] == "consent"
    assert seen["include_granted_scopes"] == "true"
    installed = installed_app_client_config(cfg)["installed"]
    assert isinstance(installed, dict)
    assert "redirect_uris" not in installed


def test_consent_flow_rejects_missing_refresh_token() -> None:
    def flow_factory(
        client_config: Mapping[str, object],
        scopes: Sequence[str],
    ) -> InstalledAppFlowLike:
        return FakeFlow(FakeConsentCredentials(refresh_token=None, scopes=list(scopes)), {})

    with pytest.raises(ConsentFailedError):
        run_installed_app_consent(
            ["s"],
            GoogleOAuthConfig(client_id="cid", client_secret="secret"),
            flow_factory=flow_factory,
            open_browser=False,
        )


def test_credentials_factory_refreshes_and_repr_does_not_leak() -> None:
    token = _stored_token(refresh_token="refresh-secret")
    store = InMemoryTokenStore(token)
    factory = GoogleCredentialsFactory(
        store,
        GoogleOAuthConfig(client_id="cid", client_secret="client-secret"),
    )

    creds = factory.authorized_credentials(request=FakeRefreshRequest(access_token="access-token"))

    assert creds.token == "access-token"
    assert "refresh-secret" not in repr(creds)
    assert "client-secret" not in repr(creds)


def test_credentials_factory_invalid_grant_requires_reauth() -> None:
    factory = GoogleCredentialsFactory(
        InMemoryTokenStore(_stored_token()),
        GoogleOAuthConfig(client_id="cid", client_secret="secret"),
    )
    original = RefreshError("invalid_grant: bad")  # type: ignore[no-untyped-call]

    with pytest.raises(ReauthRequiredError) as exc_info:
        factory.authorized_credentials(request=RaisingRefreshRequest(original))

    assert exc_info.value.__cause__ is original


def test_credentials_factory_other_refresh_error_propagates_unwrapped() -> None:
    factory = GoogleCredentialsFactory(
        InMemoryTokenStore(_stored_token()),
        GoogleOAuthConfig(client_id="cid", client_secret="secret"),
    )
    original = RefreshError("temporarily_unavailable")  # type: ignore[no-untyped-call]

    with pytest.raises(RefreshError) as exc_info:
        factory.authorized_credentials(request=RaisingRefreshRequest(original))

    assert exc_info.value is original


def test_credentials_factory_empty_store_requires_reauth_and_has_credentials() -> None:
    cfg = GoogleOAuthConfig(client_id="cid", client_secret="secret")
    empty_factory = GoogleCredentialsFactory(InMemoryTokenStore(), cfg)
    seeded_factory = GoogleCredentialsFactory(InMemoryTokenStore(_stored_token()), cfg)

    assert not empty_factory.has_credentials()
    assert seeded_factory.has_credentials()
    with pytest.raises(ReauthRequiredError):
        empty_factory.authorized_credentials(request=FakeRefreshRequest(access_token="unused"))


def test_load_oauth_config_and_repr_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "s3cr3t")

    cfg = load_oauth_config()

    assert cfg == GoogleOAuthConfig(client_id="cid", client_secret="s3cr3t")
    assert "s3cr3t" not in repr(cfg)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID")
    with pytest.raises(MissingOAuthConfigError):
        load_oauth_config()


def test_cli_status_no_account(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "build_key_provider", lambda: FakeKeyProvider(owner_unlocked=True))
    monkeypatch.setattr(cli, "build_token_store", lambda _key_provider: InMemoryTokenStore())

    assert cli.main(["status"]) == 0

    assert "no Google account paired" in capsys.readouterr().out


def test_cli_status_locked_no_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "build_key_provider", lambda: FakeKeyProvider(owner_unlocked=False))
    monkeypatch.setattr(cli, "build_token_store", lambda _key_provider: LockedTokenStore())

    assert cli.main(["status"]) == 0

    assert "locked; unlock from the iPhone to read stored Google scopes" in capsys.readouterr().out


def test_cli_revoke_locked_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "build_key_provider", lambda: FakeKeyProvider(owner_unlocked=False))
    monkeypatch.setattr(cli, "build_token_store", lambda _key_provider: LockedTokenStore())

    assert cli.main(["revoke"]) != 0

    assert "locked; unlock from the iPhone, then re-run revoke" in capsys.readouterr().out


def test_cli_login_no_scopes_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "build_key_provider", lambda: FakeKeyProvider(owner_unlocked=True))
    monkeypatch.setattr(cli, "build_token_store", lambda _key_provider: InMemoryTokenStore())

    assert cli.main(["login"]) != 0

    assert (
        "no scopes: pass --scope or ensure a connector registered scopes" in capsys.readouterr().out
    )


@dataclass(frozen=True)
class FakeConsentCredentials:
    refresh_token: str | None
    scopes: Sequence[str] | None


class FakeFlow:
    def __init__(self, creds: CredentialsLike, seen: dict[str, object]) -> None:
        self._creds = creds
        self._seen = seen

    def run_local_server(
        self,
        *,
        host: str,
        port: int,
        open_browser: bool,
        access_type: str,
        include_granted_scopes: str,
        prompt: str,
    ) -> CredentialsLike:
        self._seen.update(
            {
                "host": host,
                "port": port,
                "open_browser": open_browser,
                "access_type": access_type,
                "include_granted_scopes": include_granted_scopes,
                "prompt": prompt,
            }
        )
        return self._creds


class LockedTokenStore:
    def save(self, token: StoredToken) -> None:
        raise ScopeLockedError("locked")

    def load(self) -> StoredToken | None:
        raise ScopeLockedError("locked")

    def clear(self) -> None:
        raise ScopeLockedError("locked")


class FakeResponse(Response):
    def __init__(self, status: int, data: bytes) -> None:
        self._status = status
        self._data = data

    @property
    def status(self) -> int:
        return self._status

    @property
    def data(self) -> bytes:
        return self._data

    @property
    def headers(self) -> Mapping[str, str]:
        return {}


class FakeRefreshRequest:
    def __init__(self, *, access_token: str) -> None:
        self._access_token = access_token

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        **kwargs: object,
    ) -> FakeResponse:
        return FakeResponse(
            200,
            json.dumps(
                {
                    "access_token": self._access_token,
                    "expires_in": 3600,
                    "scope": "s",
                    "token_type": "Bearer",
                }
            ).encode("utf-8"),
        )


class RaisingRefreshRequest:
    def __init__(self, exc: RefreshError) -> None:
        self._exc = exc

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        **kwargs: object,
    ) -> FakeResponse:
        raise self._exc


def _stored_token(*, refresh_token: str = "rt") -> StoredToken:
    return StoredToken(
        refresh_token=refresh_token,
        scopes=("s",),
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid",
        obtained_at_ms=0,
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")
