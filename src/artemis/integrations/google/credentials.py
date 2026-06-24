"""Authorized Google credentials factory for connector modules."""

from __future__ import annotations

from typing import Protocol, cast

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from artemis.integrations.google.oauth import GoogleOAuthConfig
from artemis.integrations.google.tokens import TokenStore


class ReauthRequiredError(Exception):
    """Raised when the owner must re-run ``artemis-google-auth login``."""


class GoogleAuthRequestLike(Protocol):
    """Callable transport used by google-auth during refresh."""

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        **kwargs: object,
    ) -> object:
        """Perform an HTTP request for google-auth."""
        ...


class GoogleCredentialsFactory:
    """Create live auto-refreshing Google credentials from the stored token."""

    def __init__(self, token_store: TokenStore, oauth_config: GoogleOAuthConfig) -> None:
        self.token_store = token_store
        self.oauth_config = oauth_config

    def authorized_credentials(
        self,
        *,
        request: GoogleAuthRequestLike | None = None,
    ) -> Credentials:
        """Return refreshed Google credentials.

        The returned ``Credentials`` object must never be logged or sent to an
        error reporter; google-auth does not guarantee its ``repr`` redacts
        secrets in every version.
        """
        stored = self.token_store.load()
        if stored is None:
            raise ReauthRequiredError("no Google account paired; re-run artemis-google-auth login")

        creds = Credentials(  # type: ignore[no-untyped-call]
            token=None,
            refresh_token=stored.refresh_token,
            token_uri=stored.token_uri,
            client_id=self.oauth_config.client_id,
            client_secret=self.oauth_config.client_secret,
            scopes=list(stored.scopes),
        )
        transport = cast(object, request or Request())
        try:
            creds.refresh(transport)  # type: ignore[no-untyped-call]
        except RefreshError as exc:
            first_arg = str(exc.args[0]) if exc.args else ""
            if first_arg.startswith("invalid_grant"):
                raise ReauthRequiredError(
                    "stored Google refresh token was rejected; re-run artemis-google-auth login"
                ) from exc
            raise
        return creds

    def has_credentials(self) -> bool:
        """Return whether a stored Google token exists without network access."""
        return self.token_store.load() is not None
