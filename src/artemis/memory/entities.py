"""Entity repository for owner-private memory entities and aliases."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from artemis.memory.schema import now_iso

if TYPE_CHECKING:
    import sqlite3

    from artemis.ports.types import PersonId


MAX_ENTITY_TEXT = 255


class EntityType(StrEnum):
    """First-class entity types supported by the memory data layer."""

    PERSON = "person"
    PLACE = "place"
    GOAL = "goal"


@dataclass(frozen=True)
class EntityRow:
    """Mirrors a row in the ``entities`` table."""

    entity_id: str
    entity_type: EntityType
    canonical_name: str
    external_ref: str | None
    attributes: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EntityRef:
    """Cross-module logical reference to an entity."""

    module: str
    entity_id: str


class OwnerEntityError(Exception):
    """Base exception for owner-private entity data errors."""


def _normalize(text: str) -> str:
    normalized = text.strip().lower()
    if "\x00" in normalized:
        raise ValueError("entity text contains NUL byte")
    if len(normalized) > MAX_ENTITY_TEXT:
        raise ValueError("entity text exceeds 255 characters")
    return normalized


def person_fact_key(*, external_ref: str | None, name: str) -> str:
    """Return the cross-module person pointer key.

    The same email or external reference maps to the same ``person:`` key across
    modules. A name-only person gets a fresh UUID key, which is reused later via
    alias resolution. If an email is learned later, ``merge_entities`` repoints
    the name-only entity to the email-keyed identity.

    The sha256 digest here is a stable deterministic identity-correlation key,
    not a password or secret hash. The source reference is protected by the
    SQLCipher memory wall when stored in ``entities.external_ref``.
    """
    del name
    if external_ref is not None:
        normalized_ref = _normalize(external_ref)
        if normalized_ref:
            digest = hashlib.sha256(normalized_ref.encode("utf-8")).hexdigest()
            return f"person:{digest}"
    return f"person:{uuid.uuid4().hex}"


def new_entity_id(entity_type: EntityType) -> str:
    """Return a new opaque entity id with a type prefix."""
    return f"{entity_type.value}:{uuid.uuid4().hex}"


class EntityRepository:
    """Repository for resolving, aliasing, listing, and merging memory entities."""

    def __init__(self, conn: sqlite3.Connection, person_id: PersonId) -> None:
        self._conn = conn
        self._person_id = person_id

    def resolve_or_create_entity(
        self,
        name: str,
        entity_type: EntityType,
        *,
        external_ref: str | None = None,
    ) -> str:
        """Resolve an entity by external ref or alias, creating it if missing."""
        normalized_ref = _normalize(external_ref) if external_ref is not None else None
        if normalized_ref:
            row = self._conn.execute(
                "SELECT entity_id FROM entities WHERE external_ref = ?",
                (normalized_ref,),
            ).fetchone()
            if row is not None:
                return str(row[0])

        alias_id = self.resolve_alias(name)
        if alias_id is not None:
            return alias_id

        entity_id = (
            person_fact_key(external_ref=external_ref, name=name)
            if entity_type is EntityType.PERSON
            else new_entity_id(entity_type)
        )
        now = now_iso()
        with self._conn:
            self._conn.execute(
                """INSERT INTO entities (
                    entity_id, entity_type, canonical_name, external_ref,
                    attributes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?)""",
                (entity_id, entity_type.value, name, normalized_ref, now, now),
            )
            self.add_alias(name, entity_id, source="extracted")
        return entity_id

    def resolve_alias(self, text: str) -> str | None:
        """Return the entity id for a normalized alias, or ``None``."""
        row = self._conn.execute(
            "SELECT entity_id FROM entity_aliases WHERE alias = ?",
            (_normalize(text),),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def add_alias(self, alias: str, entity_id: str, *, source: str = "extracted") -> None:
        """Upsert a normalized alias for an entity."""
        with self._conn:
            self._conn.execute(
                """INSERT INTO entity_aliases (alias, entity_id, source)
                   VALUES (?, ?, ?)
                   ON CONFLICT(alias) DO UPDATE SET
                       entity_id=excluded.entity_id,
                       source=excluded.source""",
                (_normalize(alias), entity_id, source),
            )

    def list_aliases(self, entity_id: str) -> list[str]:
        """Return all normalized aliases pointing to an entity."""
        rows = self._conn.execute(
            "SELECT alias FROM entity_aliases WHERE entity_id = ? ORDER BY alias",
            (entity_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def get_entity(self, entity_id: str) -> EntityRow:
        """Return an entity row, raising ``KeyError`` on a missing id."""
        row = self._conn.execute(
            """SELECT entity_id, entity_type, canonical_name, external_ref,
                      attributes, created_at, updated_at
               FROM entities
               WHERE entity_id = ?""",
            (entity_id,),
        ).fetchone()
        if row is None:
            raise KeyError(entity_id)
        return _row_to_entity(row)

    def list_entities(self, entity_type: EntityType | None = None) -> list[EntityRow]:
        """List all entities, optionally restricted to a type."""
        if entity_type is None:
            rows = self._conn.execute(
                """SELECT entity_id, entity_type, canonical_name, external_ref,
                          attributes, created_at, updated_at
                   FROM entities
                   ORDER BY entity_id"""
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT entity_id, entity_type, canonical_name, external_ref,
                          attributes, created_at, updated_at
                   FROM entities
                   WHERE entity_type = ?
                   ORDER BY entity_id""",
                (entity_type.value,),
            ).fetchall()
        return [_row_to_entity(row) for row in rows]

    def merge_entities(self, *, keep: str, merge: str) -> None:
        """Merge one entity into another.

        Used when a name-only person later resolves to an email-keyed identity.
        Facts are not deleted; their ``subject_entity_id`` links are repointed
        from ``merge`` to ``keep``. Deleting the merged entity row is irreversible,
        so both ids are checked before any writes.
        """
        if keep == merge:
            raise ValueError("cannot merge an entity into itself")
        self.get_entity(keep)
        self.get_entity(merge)

        with self._conn:
            self._conn.execute(
                "UPDATE entity_aliases SET entity_id = ? WHERE entity_id = ?",
                (keep, merge),
            )
            self._conn.execute(
                "UPDATE facts SET subject_entity_id = ? WHERE subject_entity_id = ?",
                (keep, merge),
            )
            self._conn.execute("DELETE FROM entities WHERE entity_id = ?", (merge,))


def _row_to_entity(row: sqlite3.Row) -> EntityRow:
    return EntityRow(
        entity_id=str(row[0]),
        entity_type=EntityType(str(row[1])),
        canonical_name=str(row[2]),
        external_ref=str(row[3]) if row[3] is not None else None,
        attributes=str(row[4]) if row[4] is not None else None,
        created_at=str(row[5]),
        updated_at=str(row[6]),
    )
