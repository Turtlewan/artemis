"""Text Gateway -- attaches scope before the Brain, plus composition helper."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from artemis.brain import Brain, BrainResponse
from artemis.config import Settings, get_settings
from artemis.identity.key_provider import ScopeLockedError
from artemis.identity.scope import (
    OWNER_PERSON_ID,
    OWNER_PRIVATE,
    Identity,
    LockedError,
    primary_scope,
)
from artemis.ports.types import PersonId, Scope

if TYPE_CHECKING:
    from artemis.identity.key_provider import KeyProvider
    from artemis.ports.model import ModelPort
    from artemis.ports.retrieval import EmbeddingModel
    from artemis.registry import ToolRegistry
    from artemis.sensitivity import SensitivityClassifierProtocol

logger = logging.getLogger(__name__)

OWNER_SCOPE: Scope = OWNER_PRIVATE
"""Backward-compatible owner scope alias for existing M1 surface tests."""


class Gateway:
    """Text ingress Gateway -- attaches scope before the Brain sees the request.

    The Gateway is the single point that resolves a person to a scope and
    attaches it before the Brain (brain.md's hard ordering).
    """

    def __init__(self, brain: Brain, key_provider: KeyProvider | None = None) -> None:
        self._brain = brain
        self._key_provider = key_provider

    def _resolve_identity(self) -> Identity:
        """Resolve the owner-authenticated text-surface identity."""
        if self._key_provider is None:
            # M2-c-pending DEV STUB: until the real broker-backed KeyProvider
            # is injected by M2-c, the dev text surface is single-owner-unlocked.
            # This owner-auth seam is flagged for the M2-d security gate.
            return Identity(OWNER_PERSON_ID, "owner")
        if self._key_provider.is_owner_unlocked():
            return Identity(OWNER_PERSON_ID, "owner")
        raise LockedError("Owner session is locked")

    def _resolve_guest(self, person_id: PersonId) -> Identity:
        """Return a guest identity for the deferred voice-ID surface."""
        # M5: voice-ID will call this; no runtime caller in M2.
        return Identity(person_id, "guest")

    async def handle_text(self, request_text: str) -> BrainResponse:
        """Process a text request through the Brain with resolved scope."""
        try:
            identity = self._resolve_identity()
            scope = primary_scope(identity)
            logger.debug("Gateway: attaching resolved scope %s", scope)
            return await self._brain.respond(request_text, scope)
        except (LockedError, ScopeLockedError):
            return BrainResponse(text="LOCKED", path="locked", tool_used=None, escalated=False)

    async def handle_text_stream(self, request_text: str) -> AsyncIterator[str]:
        """Stream a text response as a single chunk for the text surface."""
        result = await self.handle_text(request_text)
        yield result.text

    async def pre_route(self, request_text: str) -> str | None:
        """Classify a request and return the top candidate tool id, if any.

        Used by the voice surface (M5-c) to classify Tier pre-serve through the
        same scope-attach seam.
        """
        try:
            identity = self._resolve_identity()
            scope = primary_scope(identity)
            logger.debug("Gateway: pre_route attaching resolved scope %s", scope)
            return await self._brain.pre_route(request_text, scope)
        except (LockedError, ScopeLockedError):
            return None


def compose_brain(
    settings: Settings | None = None,
    *,
    embedder: EmbeddingModel | None = None,
    model: ModelPort | None = None,
    key_provider: KeyProvider | None = None,
) -> Brain:
    """Build a wired Brain from settings.

    By default constructs the real adapters (``OpenAIEmbeddingModel``,
    ``OpenAIModelPort``). Pass ``embedder`` and/or ``model`` to inject doubles
    (e.g. a dev ``FakeEmbedder`` for an endpoint with no ``/embeddings``, or a
    fully offline smoke run). Uses lazy ``ToolRegistry.register()`` -- no network
    at construction time.
    """
    if settings is None:
        settings = get_settings()

    from artemis.adapters.model_adapters import OpenAIEmbeddingModel, OpenAIModelPort  # noqa: F401

    if embedder is None:
        embedder = OpenAIEmbeddingModel(settings)
    classifier: SensitivityClassifierProtocol | None = None
    if model is None:
        from artemis.adapters.composite_model import CompositeModelPort
        from artemis.sensitivity import SensitivityClassifier

        model = CompositeModelPort(settings)
        classifier = SensitivityClassifier(OpenAIModelPort(settings), settings)

    registry = _register_modules(embedder)
    from artemis.router import SemanticRouter

    memory = None
    write_queue = None
    owner_person_id = None
    if key_provider is not None:
        try:
            key_provider.dek_for_scope(OWNER_PRIVATE)
            import sqlite_vec  # type: ignore[import-untyped]

            import artemis.paths as paths
            from artemis.data.sqlcipher import sqlcipher_open
            from artemis.memory import build_write_path, memory_manifest
            from artemis.memory.repository import BitemporalRepository
            from artemis.memory.schema import create_schema
            from artemis.memory.store import SqliteMemoryStore
            from artemis.memory.write_path import MemoryWriteQueue

            db_path = paths.scope_dir(settings, OWNER_PRIVATE) / "relational" / "memory.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            dek = key_provider.dek_for_scope(OWNER_PRIVATE)
            conn = sqlcipher_open(db_path, dek.as_hex())
            conn.enable_load_extension(True)
            conn.load_extension(sqlite_vec.loadable_path())
            conn.enable_load_extension(False)
            conn.row_factory = __import__("sqlite3").Row
            create_schema(
                conn,
                embedder_model_id=settings.codex_model,
                dimension=settings.embedding_dimension,
            )
            repo = BitemporalRepository(conn, OWNER_PERSON_ID)
            registry.register(memory_manifest(repo))
            memory = SqliteMemoryStore(repo, embedder)
            write_queue = MemoryWriteQueue(build_write_path(repo, embedder, model))
            owner_person_id = OWNER_PERSON_ID
        except Exception:
            logger.warning(
                "compose_brain: memory unavailable -- building Brain without memory",
                exc_info=True,
            )
            memory = None
            write_queue = None
            owner_person_id = None

    router = SemanticRouter(registry, embedder)
    return Brain(
        router,
        registry,
        model,
        classifier=classifier,
        cloud_reasoning_enabled=settings.cloud_reasoning_enabled,
        memory=memory,
        write_queue=write_queue,
        owner_person_id=owner_person_id,
    )


def _register_modules(embedder: object) -> ToolRegistry:
    """Register all available module manifests.

    Silently skips modules not yet built (try/except ImportError), so
    ``compose_brain`` works with a partial build.

    Uses lazy ``ToolRegistry.register()`` -- no network at construction time.
    """
    from artemis.registry import ToolRegistry

    registry = ToolRegistry(embedder)  # type: ignore[arg-type]

    try:
        from artemis.tools.time_tool import manifest as time_manifest

        registry.register(time_manifest())
        logger.debug("Gateway: registered time module manifest")
    except ImportError:
        logger.debug("Gateway: time module not available -- skipping")

    return registry
