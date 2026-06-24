"""Google installed-app OAuth consent flow."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

from artemis.integrations.google.tokens import StoredToken

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class MissingOAuthConfigError(Exception):
    """Raised when Google OAuth client config is missing from the environment."""


class ConsentFailedError(Exception):
    """Raised when Google consent did not yield a usable refresh token."""


@dataclass(frozen=True)
class GoogleOAuthConfig:
    """Google installed-app OAuth client configuration."""

    client_id: str
    client_secret: str

    def __repr__(self) -> str:
        return f"GoogleOAuthConfig(client_id={self.client_id!r}, client_secret=<redacted>)"


class CredentialsLike(Protocol):
    """Subset returned by the installed-app OAuth flow."""

    @property
    def refresh_token(self) -> str | None:
        """Return the refresh token from consent."""
        ...

    @property
    def scopes(self) -> Sequence[str] | None:
        """Return granted scopes from consent."""
        ...


class InstalledAppFlowLike(Protocol):
    """Flow seam used by tests to avoid browser and network access."""

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
        """Run the loopback consent server."""
        ...


FlowFactory = Callable[[Mapping[str, object], Sequence[str]], InstalledAppFlowLike]


def load_oauth_config() -> GoogleOAuthConfig:
    """Load Google OAuth client id/secret from environment variables."""
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise MissingOAuthConfigError(
            "Google OAuth client config is missing; set GOOGLE_OAUTH_CLIENT_ID "
            "and GOOGLE_OAUTH_CLIENT_SECRET"
        )
    return GoogleOAuthConfig(client_id=client_id, client_secret=client_secret)


def installed_app_client_config(cfg: GoogleOAuthConfig) -> dict[str, object]:
    """Build the google-auth-oauthlib installed-client config shape.

    ``redirect_uris`` is deliberately omitted. ``run_local_server`` supplies the
    ephemeral loopback redirect URI at runtime.
    """
    return {
        "installed": {
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": GOOGLE_TOKEN_URI,
        }
    }


def run_installed_app_consent(
    scopes: Sequence[str],
    cfg: GoogleOAuthConfig,
    *,
    flow_factory: FlowFactory | None = None,
    open_browser: bool = True,
) -> StoredToken:
    """Run the owner-present loopback OAuth flow and return a stored token.

    The real ``InstalledAppFlow.run_local_server`` generates and validates the
    OAuth ``state`` value for CSRF protection; M8-a does not override or disable
    that library guard. PKCE is enabled when constructing the real flow.
    """
    factory = flow_factory or _real_flow_factory
    flow = factory(installed_app_client_config(cfg), list(scopes))
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=open_browser,
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    if not creds.refresh_token:
        raise ConsentFailedError(
            "Google returned no refresh token; ensure the app is Published/in "
            "production and consent used prompt=consent"
        )
    granted_scopes = tuple(creds.scopes or scopes)
    return StoredToken(
        refresh_token=creds.refresh_token,
        scopes=granted_scopes,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=cfg.client_id,
        obtained_at_ms=now_ms(),
    )


def now_ms() -> int:
    """Return the current Unix time in milliseconds."""
    return int(time.time() * 1000)


def _real_flow_factory(
    client_config: Mapping[str, object], scopes: Sequence[str]
) -> InstalledAppFlowLike:
    return cast(
        InstalledAppFlowLike,
        InstalledAppFlow.from_client_config(
            dict(client_config),
            scopes=list(scopes),
            autogenerate_code_verifier=True,
        ),
    )
