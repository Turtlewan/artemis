from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from artemis.identity.key_provider import FakeKeyProvider
from artemis.manifest import DataScope, HookSpec, ModuleManifest
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Vector
from artemis.proactive.hit_handler import HitHandler, OutboundMessage, TemplateRegistry
from artemis.proactive.hook_types import Hit, HookResult
from artemis.proactive.tier1_queue import Tier1Queue
from artemis.registry import ToolRegistry

LOGGER = logging.getLogger(__name__)


class FakeEmbedder:
    """Deterministic no-network embedder for ``ToolRegistry`` construction."""

    DIMENSION = 8

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vec(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._hash_vec(query)

    def _hash_vec(self, text: str) -> Vector:
        vec = [0.0] * self.DIMENSION
        for word in text.lower().split():
            bucket = hashlib.sha256(word.encode()).digest()[0] % self.DIMENSION
            vec[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        return [value / norm for value in vec] if norm > 0 else vec


class FakeModelPort:
    """No-network model test double."""

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        return ModelResponse(text="model line")

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        async def _stream() -> AsyncIterator[str]:
            yield "model line"

        return _stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[0.0] * 8 for _ in texts]


class SpyDelivery:
    """Captures delivery calls and confirms every message."""

    def __init__(self) -> None:
        self.messages: list[OutboundMessage] = []

    def __call__(self, messages: list[OutboundMessage]) -> int:
        self.messages.extend(messages)
        return len(messages)


def test_tier1_enqueue_coalesces_and_persists_no_payload(tmp_path: Path) -> None:
    queue = Tier1Queue(path=tmp_path / "tier1_queue.json")
    hit = _hit(result=HookResult.of({"payload": "secret"}, dedup_value="v"))

    queue.enqueue(hit)
    first_queued_at = queue.pending()[0].queued_at
    queue.enqueue(hit)

    assert len(queue.pending()) == 1
    assert queue.pending()[0].queued_at == first_queued_at
    raw = queue.path.read_bytes()
    for forbidden in (b"payload", b"result", b"urgency", b"needs_llm"):
        assert forbidden not in raw


def test_drain_confirmed_delivery_removes_without_deadlock(tmp_path: Path) -> None:
    calls = 0

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"ok": True}, dedup_value="ok")

    delivery = SpyDelivery()
    queue = Tier1Queue(path=tmp_path / "tier1_queue.json")
    queue.enqueue(_hit())

    drained = asyncio.run(
        asyncio.wait_for(
            queue._drain_async(
                registry=_registry(_manifest(hooks=[_hook(check_ref=check)])),
                key_provider=FakeKeyProvider(owner_unlocked=True),
                hit_handler=HitHandler(FakeModelPort(), TemplateRegistry(), deliver=delivery),
                logger=LOGGER,
                max_attempts=5,
            ),
            timeout=1,
        )
    )

    assert drained == 1
    assert calls == 1
    assert len(delivery.messages) == 1
    assert queue.pending() == []
    assert Tier1Queue(path=queue.path).pending() == []


def _hit(
    *,
    module: str = "finance",
    hook_name: str = "budget",
    result: HookResult | None = None,
) -> Hit:
    return Hit(
        module=module,
        hook_name=hook_name,
        tier=1,
        urgency="normal",
        needs_llm=False,
        dedup_key="budget",
        result=result or HookResult.miss(),
        delivery=None,
    )


def _hook(
    *,
    name: str = "budget",
    check_ref: object,
) -> HookSpec:
    return HookSpec(name=name, interval_seconds=60, tier=1, check_ref=check_ref, dedup_key=name)


def _manifest(*, hooks: list[HookSpec]) -> ModuleManifest:
    return ModuleManifest(
        name="finance",
        version="0.1.0",
        description="Finance",
        data_scope=DataScope.OWNER_PRIVATE,
        proactive_hooks=hooks,
    )


def _registry(manifest: ModuleManifest) -> ToolRegistry:
    registry = ToolRegistry(FakeEmbedder())
    registry.register(manifest)
    return registry
