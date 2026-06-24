"""Gmail module manifest and OAuth scope registration."""

from __future__ import annotations

from artemis.integrations.google.scopes import register_google_scopes
from artemis.manifest import DataScope, ModuleManifest, Permissions

from .cache import GmailReadCache
from .client import GMAIL_READONLY_SCOPE, GmailApiPort
from .tools import build_gmail_tools


def register_gmail_scope() -> None:
    """Register the read-only Gmail OAuth scope."""
    register_google_scopes("gmail", {GMAIL_READONLY_SCOPE})


def build_gmail_manifest(api: GmailApiPort, cache: GmailReadCache) -> ModuleManifest:
    """Return the read-only Gmail module manifest."""
    register_gmail_scope()
    return ModuleManifest(
        name="gmail",
        version="0.1.0",
        description=(
            "Read-only Gmail awareness: search, read, and surface the owner's mail "
            "(no send/modify)."
        ),
        tools=build_gmail_tools(api, cache),
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        proactive_hooks=[],
    )
