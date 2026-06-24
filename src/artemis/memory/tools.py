"""Memory entity read tools for cross-module logical references."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, ToolSpec
from artemis.memory.entities import EntityRepository
from artemis.memory.repository import BitemporalRepository


class FactView(BaseModel):
    """Owner-private current fact returned by ``resolve_entity``."""

    relation: str
    object: str
    confidence: float


class ResolveEntityArgs(BaseModel):
    """Arguments for resolving a memory-homed entity reference."""

    module: Literal["memory"] = "memory"
    entity_id: str


class ResolveEntityResult(BaseModel):
    """Resolved entity row plus current facts linked to it."""

    entity_id: str
    entity_type: str
    canonical_name: str
    aliases: list[str]
    facts: list[FactView]


class EntityNotFound(Exception):  # noqa: N818 - spec names this typed error.
    """Raised for an unknown entity id without echoing the probed id."""


async def resolve_entity(
    args: ResolveEntityArgs,
    *,
    entity_repo: EntityRepository,
    repo: BitemporalRepository,
) -> ResolveEntityResult:
    """Resolve one memory entity reference inside the owner memory store.

    ADR-013 forbids cross-store joins: the ``Literal`` on ``module`` rejects
    non-memory refs during validation, and this runtime check defends against
    validation bypass. The function is async for the ToolSpec contract, though
    the SQLite reads are synchronous.
    """
    if args.module != "memory":
        raise ValueError("resolve_entity only resolves memory-homed entities")

    try:
        entity = entity_repo.get_entity(args.entity_id)
    except KeyError:
        raise EntityNotFound("entity not found") from None

    aliases = entity_repo.list_aliases(args.entity_id)
    facts = repo.facts_for_entity(args.entity_id)
    return ResolveEntityResult(
        entity_id=args.entity_id,
        entity_type=entity.entity_type.value,
        canonical_name=entity.canonical_name,
        aliases=aliases,
        facts=[
            FactView(relation=fact.relation, object=fact.object, confidence=fact.confidence)
            for fact in facts
        ],
    )


def _bound_resolve_entity(
    repo: BitemporalRepository,
) -> Callable[[ResolveEntityArgs], Awaitable[ResolveEntityResult]]:
    """Build the hot read-path closure once for this owner repository."""
    entity_repo = EntityRepository(repo.conn, repo.person_id)

    async def _bound(args: ResolveEntityArgs) -> ResolveEntityResult:
        return await resolve_entity(args, entity_repo=entity_repo, repo=repo)

    return _bound


def memory_manifest(repo: BitemporalRepository) -> ModuleManifest:
    """Return the owner-private memory manifest bound to one repository."""
    return ModuleManifest(
        name="memory",
        version="0.1.0",
        description="owner memory + entity backbone",
        data_scope=DataScope.OWNER_PRIVATE,
        tools=[
            ToolSpec(
                name="resolve_entity",
                description=(
                    "resolve a memory-homed entity reference (person/place/goal) to its "
                    "current facts; module must be 'memory'"
                ),
                args_schema=ResolveEntityArgs,
                return_schema=ResolveEntityResult,
                callable_ref=_bound_resolve_entity(repo),
                action_risk=ActionRisk.READ,
            )
        ],
    )
