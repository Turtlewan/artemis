"""Tests for M6-c ntfy delivery, policy, and durable Tier-1 queue."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError, SecretKey
from artemis.manifest import DataScope, HookSpec, ModuleManifest
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Scope, Vector
from artemis.proactive import compose_proactive
from artemis.proactive.hit_handler import HitHandler, OutboundMessage, TemplateRegistry
from artemis.proactive.hook_types import DeliverySpec, Hit, HookResult
from artemis.proactive.ntfy_delivery import DedupStore, NtfyDelivery, _render_actions, ntfy_base_url
from artemis.proactive.policy import ProactivePolicy
from artemis.proactive.tier1_queue import Tier1Queue
from artemis.registry import ToolRegistry


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


class SpyPost:
    """Captures ntfy publish calls and returns configured HTTP statuses."""

    def __init__(self, statuses: list[int] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.statuses = list(statuses or [])

    def __call__(self, url: str, *, headers: dict[str, str], content: str) -> int:
        self.calls.append({"url": url, "headers": dict(headers), "content": content})
        if self.statuses:
            return self.statuses.pop(0)
        return 200


class RaisingOncePost:
    """Raises on the first publish and succeeds thereafter."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, url: str, *, headers: dict[str, str], content: str) -> int:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("publish failed")
        return 200


class FlappingKeyProvider:
    """Unlocked at drain entry and first hook, then locked before the second."""

    def __init__(self) -> None:
        self.calls = 0

    def is_owner_unlocked(self) -> bool:
        self.calls += 1
        return self.calls <= 2

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        raise ScopeLockedError(f"Scope is locked: {scope}")


def test_ntfy_header_mapping_and_allowed_actions(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    spy = SpyPost()
    delivery = _delivery(settings, spy)
    msg = _message(
        urgency="high",
        disposition="immediate",
        delivery=DeliverySpec(
            tags=["money"],
            click_url="http://x",
            actions=[{"action": "view", "label": "Open", "url": "artemis://finance"}],
        ),
    )

    assert delivery([msg]) == 1

    assert spy.calls[0]["url"] == f"{ntfy_base_url(settings)}/artemis-dev-secret"
    assert spy.calls[0]["content"] == msg.body
    headers = spy.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Priority"] == "high"
    assert headers["Tags"] == "money"
    assert headers["Click"] == "http://x"
    assert headers["Actions"] == "view, Open, artemis://finance"
    assert _render_actions([{"action": "view", "label": "Bad", "url": "http://x"}]) == ""


def test_urgency_priority_defaults(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    spy = SpyPost()
    delivery = _delivery(settings, spy)

    delivery([_message(urgency="normal"), _message(urgency="low", dedup_value="low")])

    assert _headers(spy, 0)["Priority"] == "default"
    assert _headers(spy, 1)["Priority"] == "low"


def test_quiet_hours_hold_and_flush(tmp_path: Path) -> None:
    now = [datetime(2026, 6, 24, 23, 30)]
    settings = _settings(tmp_path)
    spy = SpyPost()
    delivery = _delivery(settings, spy, now=lambda: now[0])

    delivery([_message(disposition="deferrable")])
    assert spy.calls == []

    delivery([_message(urgency="high", disposition="immediate", dedup_value="immediate")])
    assert len(spy.calls) == 1

    now[0] = datetime(2026, 6, 25, 7, 0)
    delivery.flush_held()
    assert len(spy.calls) == 2


def test_mute_and_module_floors_drop(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    muted = _delivery(settings, SpyPost(), policy=ProactivePolicy(muted=True))
    floor_spy = SpyPost()
    floors = _delivery(
        settings,
        floor_spy,
        policy=ProactivePolicy(module_min_urgency={"finance": "high"}),
    )

    assert muted([_message()]) == 0
    assert floors([_message(source="finance.budget", urgency="normal")]) == 0
    assert floor_spy.calls == []


def test_dedup_posts_once_across_store_instances(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    spy = SpyPost()
    delivery = _delivery(settings, spy)
    msg = _message(dedup_key="budget", dedup_value="today")

    assert delivery([msg]) == 1
    fresh = DedupStore(settings, now=lambda: datetime(2026, 6, 24, 12, 0))
    assert fresh.seen("budget", "today") is True
    assert _delivery(settings, spy, dedup=fresh)([msg]) == 0
    assert len(spy.calls) == 1


def test_tier1_enqueue_coalesces_and_persists_no_payload(tmp_path: Path) -> None:
    queue = Tier1Queue(_settings(tmp_path))
    hit = _hit(result=HookResult.of({"payload": "secret"}, dedup_value="v"))

    queue.enqueue(hit)
    first_queued_at = queue.pending()[0].queued_at
    queue.enqueue(hit)

    assert len(queue.pending()) == 1
    assert queue.pending()[0].queued_at == first_queued_at
    raw = queue.path.read_bytes()
    for forbidden in (b"payload", b"result", b"urgency", b"needs_llm"):
        assert forbidden not in raw


def test_drain_locked_then_unlocked_confirmed_delivery(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    calls = 0

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"ok": True}, dedup_value="ok")

    registry = _registry(_manifest(hooks=[_hook(check_ref=check)]))
    queue = Tier1Queue(settings)
    queue.enqueue(_hit())
    handler = _handler(_delivery(settings, SpyPost()))

    locked = FakeKeyProvider(owner_unlocked=False)
    assert (
        queue.drain(registry=registry, key_provider=locked, hit_handler=handler, logger=LOGGER) == 0
    )
    assert calls == 0

    unlocked = FakeKeyProvider(owner_unlocked=True)
    assert (
        queue.drain(registry=registry, key_provider=unlocked, hit_handler=handler, logger=LOGGER)
        == 1
    )
    assert calls == 1
    assert Tier1Queue(settings).pending() == []


def test_drain_toc_tou_rechecks_before_each_hook(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    calls: list[str] = []

    def one() -> HookResult:
        calls.append("one")
        return HookResult.miss()

    def two() -> HookResult:
        calls.append("two")
        return HookResult.miss()

    registry = _registry(
        _manifest(hooks=[_hook(name="one", check_ref=one), _hook(name="two", check_ref=two)])
    )
    queue = Tier1Queue(settings)
    queue.enqueue(_hit(hook_name="one"))
    queue.enqueue(_hit(hook_name="two"))

    queue.drain(
        registry=registry,
        key_provider=FlappingKeyProvider(),
        hit_handler=_handler(_delivery(settings, SpyPost())),
        logger=LOGGER,
    )

    assert calls == ["one"]
    assert [item.hook_name for item in queue.pending()] == ["two"]


def test_drain_dead_letters_after_max_attempts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    def raises() -> HookResult:
        raise RuntimeError("boom")

    registry = _registry(_manifest(hooks=[_hook(check_ref=raises)]))
    queue = Tier1Queue(settings)
    queue.enqueue(_hit())

    for _ in range(2):
        queue.drain(
            registry=registry,
            key_provider=FakeKeyProvider(owner_unlocked=True),
            hit_handler=_handler(_delivery(settings, SpyPost())),
            logger=LOGGER,
            max_attempts=2,
        )

    assert queue.pending() == []
    dead = json.loads(queue.dead_path.read_text(encoding="utf-8"))
    assert dead[0]["module"] == "finance"


def test_corrupt_store_recovery(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    proactive = tmp_path / "dev" / "proactive"
    proactive.mkdir(parents=True)
    (proactive / "tier1_queue.json").write_text("{", encoding="utf-8")
    (proactive / "dedup.json").write_text("{", encoding="utf-8")
    (proactive / "held.json").write_text("{", encoding="utf-8")

    assert Tier1Queue(settings).pending() == []
    assert DedupStore(settings).seen("k", "v") is False
    delivery = _delivery(settings, SpyPost())
    assert delivery._load_held() == []
    assert list(proactive.glob("tier1_queue.json.corrupt.*"))


def test_held_ttl_drops_stale_entries(tmp_path: Path) -> None:
    now = datetime(2026, 6, 24, 23, 0)
    settings = _settings(tmp_path)
    spy = SpyPost()
    delivery = _delivery(
        settings,
        spy,
        now=lambda: now + timedelta(hours=10),
        policy=ProactivePolicy(held_ttl_hours=1),
    )
    delivery.held_path.parent.mkdir(parents=True, exist_ok=True)
    delivery.held_path.write_text(
        json.dumps(
            [
                {
                    "title": "Old",
                    "body": "old",
                    "urgency": "normal",
                    "disposition": "deferrable",
                    "tier": 0,
                    "dedup_key": None,
                    "dedup_value": None,
                    "source": "finance.budget",
                    "held_at": now.isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )

    delivery.flush_held()

    assert spy.calls == []
    assert json.loads(delivery.held_path.read_text(encoding="utf-8")) == []


def test_compose_proactive_wires_heartbeat(tmp_path: Path) -> None:
    heartbeat = compose_proactive(
        _settings(tmp_path),
        _registry(_manifest(hooks=[])),
        FakeKeyProvider(owner_unlocked=True),
        FakeModelPort(),
    )

    assert heartbeat._on_hits is not None
    assert heartbeat._tier1_sink is not None
    assert len(heartbeat.pre_tick_steps) == 2


@pytest.mark.asyncio
async def test_compose_pre_tick_steps_order_and_degrade(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    calls: list[str] = []

    def drain_check() -> HookResult:
        calls.append("drain")
        return HookResult.miss()

    def tick_check() -> HookResult:
        calls.append("tick")
        return HookResult.miss()

    registry = _registry(
        _manifest(
            hooks=[
                _hook(name="drain_hook", check_ref=drain_check),
                _hook(name="tick_hook", check_ref=tick_check),
            ]
        )
    )
    Tier1Queue(settings).enqueue(_hit(hook_name="drain_hook"))

    async def raising_step() -> None:
        calls.append("raising")
        raise RuntimeError("pre step")

    async def async_noop() -> None:
        calls.append("noop")

    heartbeat = compose_proactive(
        settings,
        registry,
        FakeKeyProvider(owner_unlocked=True),
        FakeModelPort(),
        pre_tick_steps=[raising_step, async_noop],
    )

    assert heartbeat.pre_tick_steps[0].__name__ == "_flush_step"
    assert heartbeat.pre_tick_steps[1].__name__ == "_drain_step"
    await heartbeat.run_forever(max_ticks=1, sleep_seconds=0.0)

    assert calls == ["drain", "raising", "noop", "drain", "tick"]


def test_tier1_deferrable_not_held_during_quiet_hours(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    spy = SpyPost()
    delivery = _delivery(settings, spy, now=lambda: datetime(2026, 6, 24, 23, 0))

    assert delivery([_message(tier=1, disposition="deferrable")]) == 1

    assert len(spy.calls) == 1
    if delivery.held_path.exists():
        held = json.loads(delivery.held_path.read_text(encoding="utf-8"))
        assert all(entry.get("tier") != 1 for entry in held)


def test_raising_publish_does_not_abort_batch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    raising = RaisingOncePost()
    delivery = _delivery(settings, raising)

    assert delivery([_message(dedup_value="one"), _message(dedup_value="two")]) == 1
    assert raising.calls == 2


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_root=tmp_path,
        slot="dev",
        ntfy_port=8050,
        ntfy_topic_secret="secret",
        roles={},
    )


def _delivery(
    settings: Settings,
    spy: Any,
    *,
    policy: ProactivePolicy | None = None,
    dedup: DedupStore | None = None,
    now: Any | None = None,
) -> NtfyDelivery:
    clock = now or (lambda: datetime(2026, 6, 24, 12, 0))
    return NtfyDelivery(
        settings,
        policy or ProactivePolicy(),
        dedup or DedupStore(settings, now=clock),
        now=clock,
        http_post=spy,
    )


def _message(
    *,
    urgency: str = "normal",
    disposition: str = "deferrable",
    tier: int = 0,
    delivery: DeliverySpec | None = None,
    dedup_key: str | None = "key",
    dedup_value: str | None = "value",
    source: str = "finance.budget",
) -> OutboundMessage:
    return OutboundMessage(
        title="Budget",
        body="Budget update",
        urgency=_urgency(urgency),
        disposition=_disposition(disposition),
        tier=0 if tier == 0 else 1,
        delivery=delivery,
        dedup_key=dedup_key,
        dedup_value=dedup_value,
        source=source,
    )


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
    check_ref: Any,
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


def _handler(delivery: NtfyDelivery) -> HitHandler:
    return HitHandler(FakeModelPort(), TemplateRegistry(), deliver=delivery)


def _headers(spy: SpyPost, index: int) -> dict[str, str]:
    headers = spy.calls[index]["headers"]
    assert isinstance(headers, dict)
    return {str(key): str(value) for key, value in headers.items()}


def _urgency(value: str) -> Any:
    return value


def _disposition(value: str) -> Any:
    return value


LOGGER = __import__("logging").getLogger(__name__)
