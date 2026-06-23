"""Owner/guest identity model and scope resolution helpers.

The wall invariant lives here: guests resolve only to their own ``guest-*``
scope and never to owner scopes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from artemis.ports.types import PersonId, Scope

Role = Literal["owner", "guest"]

OWNER_PERSON_ID: PersonId = PersonId("owner")
OWNER_PRIVATE: Scope = "owner-private"
GENERAL: Scope = "general"


class LockedError(Exception):
    """Raised when a request reaches a locked owner-authenticated surface."""


@dataclass(frozen=True)
class Identity:
    """Resolved caller identity."""

    person_id: PersonId
    role: Role

    def __post_init__(self) -> None:
        if not str(self.person_id):
            raise ValueError("person_id must not be empty")
        if self.role not in ("owner", "guest"):
            raise ValueError(f"Unknown role: {self.role!r}")


def owner_scopes() -> tuple[Scope, ...]:
    """Return scopes available to the owner."""
    return (OWNER_PRIVATE, GENERAL)


def guest_scope(person_id: PersonId) -> Scope:
    """Return the isolated guest scope for a person."""
    raw_person_id = str(person_id)
    if not raw_person_id:
        raise ValueError("guest person_id must not be empty")
    if raw_person_id.startswith("guest-"):
        raise ValueError("guest person_id must not include the guest- scope prefix")
    if raw_person_id in owner_scopes():
        raise ValueError("guest person_id must not be an owner scope")
    return f"guest-{raw_person_id}"


def primary_scope(identity: Identity) -> Scope:
    """Return the primary scope attached to a request from this identity."""
    if identity.role == "owner":
        return OWNER_PRIVATE
    if identity.role == "guest":
        return guest_scope(identity.person_id)
    raise ValueError(f"Unknown role: {identity.role!r}")


def scopes_for(identity: Identity) -> tuple[Scope, ...]:
    """Return every scope this identity may access."""
    if identity.role == "owner":
        return owner_scopes()
    if identity.role == "guest":
        return (guest_scope(identity.person_id),)
    raise ValueError(f"Unknown role: {identity.role!r}")
