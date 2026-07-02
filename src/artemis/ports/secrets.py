"""Secret storage port.

Implementations must never log or otherwise disclose secret values. Names are
metadata; values belong only in the underlying secret backend.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretStorePort(Protocol):
    """Port for storing owner secrets without exposing secret values."""

    def get(self, name: str) -> str | None:
        """Return a secret value by name, or None when absent."""
        ...

    def set(self, name: str, value: str) -> None:
        """Store a secret value.

        Implementations must keep values out of logs, errors, and any names
        index used for listing.
        """
        ...

    def delete(self, name: str) -> None:
        """Delete a secret value if present."""
        ...

    def list_names(self) -> list[str]:
        """List known secret names only, never values."""
        ...
