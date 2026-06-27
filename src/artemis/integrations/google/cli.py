"""Owner-present CLI for pairing and managing Google OAuth consent."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from artemis.config import get_settings
from artemis.identity.key_provider import KeyProvider, ScopeLockedError
from artemis.identity.owner_provider import build_owner_key_provider
from artemis.identity.windows_key_provider import UnlockDeniedError, UnlockUnavailableError
from artemis.integrations.google.credentials import GoogleCredentialsFactory
from artemis.integrations.google.oauth import (
    GoogleOAuthConfig,
    MissingOAuthConfigError,
    load_oauth_config,
    run_installed_app_consent,
)
from artemis.integrations.google.scopes import required_scopes
from artemis.integrations.google.tokens import SqlCipherTokenStore, TokenStore

logger = logging.getLogger(__name__)


def build_key_provider() -> KeyProvider:
    """Build the owner-present key provider."""
    return build_owner_key_provider(get_settings())


def build_token_store(key_provider: KeyProvider) -> TokenStore:
    """Build the production owner-private token store."""
    return SqlCipherTokenStore(get_settings(), key_provider)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``artemis-google-auth`` CLI."""
    parser = argparse.ArgumentParser(prog="artemis-google-auth")
    subcommands = parser.add_subparsers(dest="command", required=True)

    login = subcommands.add_parser("login")
    login.add_argument("--scope", action="append", default=[])

    subcommands.add_parser("status")
    subcommands.add_parser("revoke")

    args = parser.parse_args(argv)

    try:
        key_provider = build_key_provider()
    except (UnlockUnavailableError, UnlockDeniedError) as exc:
        logger.warning("artemis-google-auth unlock failed: %s: %s", type(exc).__name__, exc)
        print("Unlock failed.")
        return 2
    store = build_token_store(key_provider)

    if args.command == "login":
        scopes = tuple(args.scope or sorted(required_scopes()))
        if not scopes:
            print("no scopes: pass --scope or ensure a connector registered scopes")
            return 2
        if not key_provider.is_owner_unlocked():
            print("Vault is locked; unlock from the iPhone, then retry")
            return 1
        cfg = load_oauth_config()
        token = run_installed_app_consent(scopes, cfg)
        store.save(token)
        print(f"Google account paired with scopes: {', '.join(token.scopes)}")
        return 0

    if args.command == "status":
        try:
            factory = GoogleCredentialsFactory(store, load_oauth_config_for_status())
            if not factory.has_credentials():
                print("no Google account paired")
                return 0
            status_token = store.load()
        except ScopeLockedError:
            print("locked; unlock from the iPhone to read stored Google scopes")
            return 0
        if status_token is None:
            print("no Google account paired")
            return 0
        obtained = datetime.fromtimestamp(status_token.obtained_at_ms / 1000, UTC).isoformat()
        print(
            f"Google account paired; scopes: {', '.join(status_token.scopes)}; "
            f"obtained_at: {obtained}"
        )
        return 0

    if args.command == "revoke":
        try:
            store.clear()
        except ScopeLockedError:
            print("locked; unlock from the iPhone, then re-run revoke")
            return 1
        print("Google token removed; also remove Artemis access at myaccount.google.com")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def load_oauth_config_for_status() -> GoogleOAuthConfig:
    """Return OAuth config for status without requiring env when only checking storage.

    ``has_credentials`` does not perform network access or inspect OAuth config,
    but the factory constructor requires one. This avoids making ``status``
    depend on env secrets when reporting an empty store.
    """
    try:
        return load_oauth_config()
    except MissingOAuthConfigError:
        return GoogleOAuthConfig(client_id="", client_secret="")
