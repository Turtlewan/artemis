"""``artemis-unlock`` — provision + Windows Hello unlock the owner-private key store.

A thin owner-present utility (m2-win-b, ADR-033): provision sealed DEKs if missing,
run the Hello gesture, report how many scopes unlocked, then re-lock. It never
prints key material, and on failure emits only a generic message — the specific
reason (not enrolled vs gesture denied vs no console) is logged at WARNING for the
local owner, never surfaced to stdout, so the CLI does not leak which gate failed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from artemis.config import get_settings
from artemis.identity.windows_hello import HelloError
from artemis.identity.windows_key_provider import (
    UnlockDeniedError,
    UnlockUnavailableError,
    WindowsKeyProvider,
)

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Provision, Hello-unlock, report the scope count, and re-lock.

    Returns 0 on a verified unlock, 2 on any failure (generic stdout message).
    """
    settings = get_settings()
    provider = WindowsKeyProvider(settings)
    provider.provision()
    try:
        provider.unlock()
    except (UnlockUnavailableError, UnlockDeniedError, HelloError) as exc:
        logger.warning("artemis-unlock failed: %s: %s", type(exc).__name__, exc)
        print("Unlock failed.")
        return 2

    try:
        print(f"unlocked: {provider.unlocked_scope_count} scope(s)")
    finally:
        provider.lock()  # never leave scope keys resident after the report
    return 0
