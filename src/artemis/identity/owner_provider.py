"""Platform factory for owner-present key providers."""

from __future__ import annotations

import sys

from artemis.config import Settings
from artemis.identity.key_provider import KeyProvider

_BROKER_UNBUILT_MESSAGE = "Google auth CLI requires the broker-backed KeyProvider factory"


def build_owner_key_provider(settings: Settings) -> KeyProvider:
    """Build and unlock the owner-private key provider for this platform."""
    if sys.platform != "win32":
        raise RuntimeError(_BROKER_UNBUILT_MESSAGE)

    from artemis.identity.windows_key_provider import WindowsKeyProvider

    provider = WindowsKeyProvider(settings)
    provider.provision()
    provider.unlock()
    return provider
