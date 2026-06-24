"""Proactive engine composition entry point and hook contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artemis.config import Settings
    from artemis.heartbeat import Heartbeat
    from artemis.identity.key_provider import KeyProvider
    from artemis.ports.model import ModelPort
    from artemis.registry import ToolRegistry


def compose_proactive(
    settings: Settings,
    registry: ToolRegistry,
    key_provider: KeyProvider,
    model: ModelPort,
    *,
    pre_tick_steps: list[Callable[[], Awaitable[None]]] | None = None,
) -> Heartbeat:
    """Compose the proactive engine a future daemon mount should call."""
    from artemis.heartbeat import Heartbeat
    from artemis.proactive.hit_handler import HitHandler, TemplateRegistry
    from artemis.proactive.hook_types import TickResult
    from artemis.proactive.ntfy_delivery import DedupStore, NtfyDelivery
    from artemis.proactive.policy import load_policy
    from artemis.proactive.tier1_queue import Tier1Queue, attach_to_heartbeat

    policy = load_policy(settings)
    dedup = DedupStore(settings)
    ntfy = NtfyDelivery(settings, policy, dedup)
    templates = TemplateRegistry()
    hit_handler = HitHandler(model, templates, deliver=ntfy)

    async def _on_hits(tick: TickResult) -> None:
        await hit_handler.handle(tick)

    queue = Tier1Queue(settings)
    heartbeat = Heartbeat(
        registry,
        key_provider,
        on_hits=_on_hits,
        tier1_sink=queue.enqueue,
    )
    attach_to_heartbeat(
        heartbeat,
        queue,
        ntfy,
        registry,
        key_provider,
        hit_handler,
        pre_tick_steps=pre_tick_steps,
    )
    return heartbeat
