"""Text Gateway -- attaches scope before the Brain, plus composition helper."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Final, cast

from artemis.brain import Brain, BrainResponse
from artemis.config import Settings, get_settings
from artemis.identity.key_provider import ScopeLockedError
from artemis.identity.scope import (
    OWNER_PERSON_ID as _OWNER_PERSON_ID,
)
from artemis.identity.scope import (
    OWNER_PRIVATE,
    Identity,
    LockedError,
    primary_scope,
)
from artemis.identity.tier import tier_for
from artemis.manifest import DataScope
from artemis.ports.types import PersonId, Scope
from artemis.ports.voice import SpeakerID
from artemis.speakable import DisplaySeg, SpeakSeg, classify_shape, subject_phrase, to_speakable

if TYPE_CHECKING:
    from artemis.identity.key_provider import KeyProvider
    from artemis.ports.model import ModelPort
    from artemis.ports.retrieval import EmbeddingModel, Reranker
    from artemis.ports.types import Fact, RetrievedChunk
    from artemis.registry import ToolRegistry
    from artemis.sensitivity import ReleaseAuditEntry, SensitivityClassifierProtocol

logger = logging.getLogger(__name__)
_STREAM_END: Final = object()
type _QueueItem = str | BaseException | object

OWNER_PERSON_ID: PersonId = _OWNER_PERSON_ID
"""Backward-compatible owner person id alias for auth and gateway callers."""

GUEST_PERSON_ID: PersonId = PersonId("guest")
"""Shared least-privilege guest person id for unknown voice speakers."""

OWNER_SCOPE: Scope = OWNER_PRIVATE
"""Backward-compatible owner scope alias for existing M1 surface tests."""

NEEDS_UNLOCK_PROMPT: str = "That needs your phone unlock first."
"""Spoken voice prompt for locked owner Tier-1 requests."""


class NeedsPhoneUnlock(RuntimeError):  # noqa: N818 - spec requires this import name.
    """Raised when a voice turn needs owner key unlock before serving Tier-1 data."""


class _StreamTee:
    """Tee one Brain stream into display chunks and one optional speakable result."""

    def __init__(
        self,
        source: AsyncIterator[str],
        *,
        speak: bool,
        subject: str | None,
    ) -> None:
        self._source = source
        self._speak = speak
        self._subject = subject
        self._display_queue: asyncio.Queue[_QueueItem] = asyncio.Queue()
        self._speak_queue: asyncio.Queue[_QueueItem] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def display(self) -> AsyncIterator[DisplaySeg]:
        return self._display_iter()

    def speak(self) -> AsyncIterator[SpeakSeg]:
        if not self._speak:
            return self._empty_speak_iter()
        return self._speak_iter()

    def _ensure_started(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._produce())

    async def _produce(self) -> None:
        answer_parts: list[str] = []
        pointer_sent = False
        try:
            async for chunk in self._source:
                await self._display_queue.put(chunk)
                if self._speak:
                    answer_parts.append(chunk)
                    answer = "".join(answer_parts)
                    if not pointer_sent and classify_shape(answer) == "pointer":
                        await self._speak_queue.put(to_speakable(answer, subject=self._subject))
                        pointer_sent = True
            if self._speak and not pointer_sent:
                await self._speak_queue.put(
                    to_speakable("".join(answer_parts), subject=self._subject)
                )
        except Exception as exc:
            await self._display_queue.put(exc)
            if self._speak:
                await self._speak_queue.put(exc)
        finally:
            await self._display_queue.put(_STREAM_END)
            if self._speak:
                await self._speak_queue.put(_STREAM_END)

    async def _display_iter(self) -> AsyncIterator[DisplaySeg]:
        self._ensure_started()
        while True:
            item = await self._display_queue.get()
            if item is _STREAM_END:
                return
            if isinstance(item, BaseException):
                raise item
            yield cast(str, item)

    async def _speak_iter(self) -> AsyncIterator[SpeakSeg]:
        self._ensure_started()
        while True:
            item = await self._speak_queue.get()
            if item is _STREAM_END:
                return
            if isinstance(item, BaseException):
                raise item
            yield cast(str, item)

    async def _empty_speak_iter(self) -> AsyncIterator[SpeakSeg]:
        if False:
            yield ""


class Gateway:
    """Text ingress Gateway -- attaches scope before the Brain sees the request.

    The Gateway is the single point that resolves a person to a scope and
    attaches it before the Brain (brain.md's hard ordering).
    """

    def __init__(
        self,
        brain: Brain,
        key_provider: KeyProvider | None = None,
        speaker_id: SpeakerID | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._brain = brain
        self._key_provider = key_provider
        self._speaker_id = speaker_id
        if self._speaker_id is None and key_provider is not None and settings is not None:
            from artemis.voice.speaker_id import EcapaSpeakerID, VoiceprintStore

            self._speaker_id = EcapaSpeakerID(VoiceprintStore(settings, key_provider))

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

    def _resolve_voice_identity(self, audio: bytes) -> Identity:
        """Resolve voice identity without treating voice-ID as key unlock."""
        if self._speaker_id is None:
            return self._resolve_guest(GUEST_PERSON_ID)
        person_id = self._speaker_id.identify(audio)
        if person_id == OWNER_PERSON_ID:
            return Identity(OWNER_PERSON_ID, "owner")
        if person_id is not None:
            return self._resolve_guest(person_id)
        return self._resolve_guest(GUEST_PERSON_ID)

    async def handle_text(
        self,
        request_text: str,
        released_ref_ids: frozenset[str] = frozenset(),
    ) -> BrainResponse:
        """Process a text request through the Brain with resolved scope."""
        try:
            identity = self._resolve_identity()
            scope = primary_scope(identity)
            logger.debug("Gateway: attaching resolved scope %s", scope)
            return await self.handle_text_scoped(request_text, scope, released_ref_ids)
        except (LockedError, ScopeLockedError):
            return BrainResponse(text="LOCKED", path="locked", tool_used=None, escalated=False)

    async def handle_text_scoped(
        self,
        request_text: str,
        scope: Scope,
        released_ref_ids: frozenset[str] = frozenset(),
    ) -> BrainResponse:
        """Process a text request through the Brain with an authenticated scope."""
        if released_ref_ids:
            return await self._brain.respond(request_text, scope, released_ref_ids)
        return await self._brain.respond(request_text, scope)

    async def handle_text_stream(self, request_text: str) -> AsyncIterator[str]:
        """Stream a text response as a single chunk for the text surface."""
        result = await self.handle_text(request_text)
        yield result.text

    async def handle_text_stream_scoped(
        self,
        request_text: str,
        scope: Scope,
    ) -> AsyncIterator[str]:
        """Stream a text response through the Brain with an authenticated scope."""
        async for chunk in self._brain.respond_stream(request_text, scope):
            yield chunk

    async def handle_ask_unified(
        self,
        query: str,
        *,
        scope_or_identity: Scope | Identity,
        speak: bool,
    ) -> tuple[AsyncIterator[DisplaySeg], AsyncIterator[SpeakSeg]]:
        """Run one Brain stream and return display plus optional speak iterators."""
        if isinstance(scope_or_identity, Identity):
            identity = scope_or_identity
            scope = primary_scope(identity)
            module_fq = await self._brain.pre_route(query, scope)
            data_scope = self._data_scope_for_module(module_fq)
            tier = tier_for(data_scope)
            if identity.role == "owner" and tier == "tier1":
                if self._key_provider is None or not self._key_provider.is_owner_unlocked():
                    raise NeedsPhoneUnlock
        else:
            scope = scope_or_identity
        tee = _StreamTee(
            self._brain.respond_stream(query, scope),
            speak=speak,
            subject=subject_phrase(query),
        )
        return tee.display(), tee.speak()

    async def handle_voice(self, audio: bytes, transcript: str) -> BrainResponse:
        """Process a voice turn after speaker-ID scope attach.

        Voice-ID routes identity but never unlocks the owner DEK. Owner Tier-1
        requests while locked return a phone-unlock prompt before any Brain
        response can serve sensitive owner data.
        """
        identity = self._resolve_voice_identity(audio)
        scope = primary_scope(identity)
        module_fq = await self._brain.pre_route(transcript, scope)
        data_scope = self._data_scope_for_module(module_fq)
        tier = tier_for(data_scope)
        if identity.role == "owner" and tier == "tier1":
            if self._key_provider is None or not self._key_provider.is_owner_unlocked():
                return BrainResponse(
                    text="NEEDS_PHONE_UNLOCK",
                    path="needs-unlock",
                    tool_used=None,
                    escalated=False,
                )
        return await self._brain.respond(transcript, scope)

    async def handle_voice_stream(self, audio: bytes, transcript: str) -> AsyncIterator[str]:
        """Stream a voice response after fail-closed voice-ID and Tier gating.

        Voice-ID resolves identity only; owner Tier-1 requests require a real
        unlocked key provider before any streamed Brain response can start.
        """
        identity = self._resolve_voice_identity(audio)
        scope = primary_scope(identity)
        module_fq = await self._brain.pre_route(transcript, scope)
        data_scope = self._data_scope_for_module(module_fq)
        tier = tier_for(data_scope)
        if identity.role == "owner" and tier == "tier1":
            if self._key_provider is None or not self._key_provider.is_owner_unlocked():
                raise NeedsPhoneUnlock
        async for chunk in self._brain.respond_stream(transcript, scope):
            yield chunk

    def _data_scope_for_module(self, module_fq: str | None) -> DataScope | None:
        if module_fq is None:
            return None
        module_name = module_fq.split(".", 1)[0]
        manifest = self._brain._registry.manifests().get(module_name)
        if manifest is None:
            return None
        return manifest.data_scope

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
    reranker: Reranker | None = None,
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
    enforcer = None
    retrieve_fn = None
    agentic = None
    recall_fn = None
    audit_log = None
    if model is None:
        from artemis.adapters.composite_model import CompositeModelPort
        from artemis.sensitivity import SensitivityClassifier, SensitivityEnforcer

        model = CompositeModelPort(settings)
        classifier = SensitivityClassifier(OpenAIModelPort(settings), settings)
        enforcer = SensitivityEnforcer(
            classifier,
            cloud_reasoning_enabled=settings.cloud_reasoning_enabled,
        )

    registry = _register_modules(embedder, settings=settings, key_provider=key_provider)
    from artemis.router import SemanticRouter

    memory = None
    write_queue = None
    owner_person_id = None
    if key_provider is not None:
        try:
            key_provider.dek_for_scope(OWNER_PRIVATE)
            import sqlite_vec  # type: ignore[import-untyped]

            import artemis.paths as paths
            from artemis.adapters.lancedb_store import LanceDBVectorStore
            from artemis.adapters.reranker import FakeReranker
            from artemis.data.sqlcipher import set_row_factory, sqlcipher_open
            from artemis.identity.scope import GENERAL
            from artemis.memory import build_write_path, memory_manifest
            from artemis.memory.repository import BitemporalRepository
            from artemis.memory.schema import create_schema
            from artemis.memory.store import SqliteMemoryStore
            from artemis.memory.write_path import MemoryWriteQueue
            from artemis.retrieval.agentic import AgenticRetriever
            from artemis.retrieval.retriever import AdaptiveRetriever

            db_path = paths.scope_dir(settings, OWNER_PRIVATE) / "relational" / "memory.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            dek = key_provider.dek_for_scope(OWNER_PRIVATE)
            conn = sqlcipher_open(db_path, dek.as_hex())
            conn.enable_load_extension(True)
            conn.load_extension(sqlite_vec.loadable_path())
            conn.enable_load_extension(False)
            set_row_factory(conn)
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
            memory_store = memory

            async def recall_fn() -> list[Fact]:
                return await memory_store.inject_context(OWNER_PERSON_ID, 512)

            store_owner = LanceDBVectorStore(
                OWNER_PRIVATE,
                settings,
                settings.codex_model,
                settings.embedding_dimension,
                is_unlocked=key_provider.is_owner_unlocked,
            )
            store_general = LanceDBVectorStore(
                GENERAL,
                settings,
                settings.codex_model,
                settings.embedding_dimension,
                is_unlocked=lambda: True,
            )
            stores: dict[str, LanceDBVectorStore] = {
                OWNER_PRIVATE: store_owner,
                GENERAL: store_general,
            }

            def store_for(scope: str) -> LanceDBVectorStore:
                store = stores.get(scope)
                if store is None:
                    raise ValueError(f"No store for scope: {scope!r}")
                return store

            retriever = AdaptiveRetriever(
                embedder,
                store_for,
                reranker if reranker is not None else FakeReranker(),
            )
            agentic = AgenticRetriever(retriever, model)

            async def retrieve_fn(query: str) -> list[RetrievedChunk]:
                import asyncio

                owner_chunks, general_chunks = await asyncio.gather(
                    retriever.retrieve(query, OWNER_PRIVATE),
                    retriever.retrieve(query, GENERAL),
                )
                seen: set[str] = set()
                merged: list[RetrievedChunk] = []
                for chunk in owner_chunks + general_chunks:
                    if chunk.chunk.chunk_id in seen:
                        continue
                    seen.add(chunk.chunk.chunk_id)
                    merged.append(chunk)
                return merged

        except Exception:
            logger.warning(
                "compose_brain: memory unavailable -- building Brain without memory",
                exc_info=True,
            )
            memory = None
            write_queue = None
            owner_person_id = None

    if enforcer is not None:
        import artemis.paths as paths

        audit_path = (
            paths.scope_dir(settings, OWNER_PRIVATE) / "audit" / "sensitivity_releases.jsonl"
        )

        def audit_log(entry: ReleaseAuditEntry) -> None:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "query_id": entry.query_id,
                            "ref_id": entry.ref_id,
                            "kind": entry.kind,
                            "released_at": entry.released_at,
                            "category": entry.category,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )

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
        agentic=agentic,
        enforcer=enforcer,
        retrieve_fn=retrieve_fn,
        recall_fn=recall_fn,
        audit_log=audit_log,
    )


def _register_modules(
    embedder: object,
    *,
    settings: Settings | None = None,
    key_provider: KeyProvider | None = None,
) -> ToolRegistry:
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

    if key_provider is not None:
        try:
            from artemis.modules.productivity import ProductivityStore, tasks_manifest

            productivity_settings = settings if settings is not None else get_settings()
            store = ProductivityStore(productivity_settings, key_provider)
            registry.register(tasks_manifest(store, include_write_surface=False))
            logger.debug("Gateway: registered tasks module manifest")
        except ImportError:
            logger.debug("Gateway: tasks module not available -- skipping")

        if key_provider.is_owner_unlocked():
            try:
                from artemis.modules.finance import FinanceStore, finance_manifest

                finance_settings = settings if settings is not None else get_settings()
                finance_store = FinanceStore(finance_settings, key_provider)
                registry.register(finance_manifest(finance_store, include_write_surface=False))
                logger.debug("Gateway: registered finance module manifest")
            except ImportError:
                logger.debug("Gateway: finance module not available -- skipping")
        else:
            logger.debug("Gateway: owner locked -- skipping finance module manifest")

    return registry
