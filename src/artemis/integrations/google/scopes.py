"""Scope registry used by Google connector modules.

M8-a is scope-agnostic: connector specs register their own least-privilege
Google scopes here, and the owner-present consent CLI grants the union.
"""

from __future__ import annotations

from collections.abc import Iterable

_REGISTRY: dict[str, frozenset[str]] = {}


def register_google_scopes(connector: str, scopes: Iterable[str]) -> None:
    """Register the Google OAuth scopes required by one connector."""
    if not connector:
        raise ValueError("connector must be non-empty")
    validated = frozenset(_validate_scope(scope) for scope in scopes)
    _REGISTRY[connector] = validated


def required_scopes() -> frozenset[str]:
    """Return the sorted union of every registered connector scope."""
    return frozenset(sorted(scope for scopes in _REGISTRY.values() for scope in scopes))


def clear_registry() -> None:
    """Clear the process-local registry.

    Test-only seam: production code should register connector scopes at import
    or module setup time and should not clear them.
    """
    _REGISTRY.clear()


def _validate_scope(scope: str) -> str:
    if not isinstance(scope, str):
        raise ValueError("scope must be a string")
    if scope in {"openid", "email", "profile"}:
        return scope
    if scope.startswith("https://") and scope.strip() == scope and len(scope) > len("https://"):
        return scope
    raise ValueError(f"malformed Google OAuth scope: {scope!r}")
