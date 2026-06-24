"""Gmail urgency hook factory.

The hook uses an async pre-flight to fetch DR-a quarantined extracts, stores
them in a small cell, then exposes a synchronous ``check_ref`` for the heartbeat
tick. ``check_ref`` is deterministic and LLM-free. Callers must register the
returned template callback with M6-b's ``TemplateRegistry`` before the first
tick and pass the returned pre-flight as an M6-c ``pre_tick_steps`` entry.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import date

from artemis.manifest import HookSpec
from artemis.modules.gmail.cache import GmailReadCache
from artemis.modules.gmail.client import GmailApiPort
from artemis.modules.gmail.urgency import (
    GmailUrgencyPreFilter,
    UrgencyTemplateRenderer,
    fetch_extracts,
)
from artemis.ports.memory import MemoryStore
from artemis.ports.types import PersonId
from artemis.proactive.hit_handler import TemplateRegistry
from artemis.proactive.hook_types import DeliverySpec, HookResult
from artemis.runtime_config import get_runtime_config
from artemis.untrusted.quarantine import Extract, QuarantinedReader

logger = logging.getLogger(__name__)


async def build_known_senders(
    memory: MemoryStore | None,
    person_id: PersonId,
    k: int = 20,
) -> frozenset[str]:
    """Build lowercased sender tokens from memory at composition time only."""
    if memory is None:
        return frozenset()
    try:
        facts = await memory.recall(
            person_id,
            query="known contact person name",
            k=k,
            as_of=None,
        )
    except Exception as exc:
        logger.warning("Gmail urgency known-sender recall failed: %s", type(exc).__name__)
        return frozenset()

    tokens: set[str] = set()
    for fact in facts:
        for token in re.split(r"[\s,]+", f"{fact.subject} {fact.object}".lower()):
            stripped = token.strip()
            if stripped:
                tokens.add(stripped)
    return frozenset(tokens)


def build_gmail_urgency_hook(
    cache: GmailReadCache,
    api: GmailApiPort,
    reader: QuarantinedReader,
    known_senders: frozenset[str],
    *,
    max_candidates: int = 10,
    interval_seconds: int = 300,
) -> tuple[
    HookSpec,
    Callable[[], Awaitable[None]],
    Callable[[TemplateRegistry], None],
]:
    """Return the urgency HookSpec, async pre-flight, and template registrar.

    Runtime Gmail tunables are read once at hook-build time. Rebuild this hook
    after a runtime-config reload to pick up changed keyword, VIP, or exclude
    lists.
    """
    cfg = get_runtime_config().gmail
    urgency_keywords = frozenset(keyword.lower() for keyword in cfg.urgency_keywords)
    static_vips = frozenset(vip.lower() for vip in cfg.vip_senders)
    sender_exclude = frozenset(domain.lower() for domain in cfg.urgency_sender_exclude)
    vip_senders = static_vips | known_senders
    extract_cell: list[dict[str, Extract]] = [{}]
    pre_filter = GmailUrgencyPreFilter(
        cache,
        known_senders=known_senders,
        urgency_keywords=urgency_keywords,
        vip_senders=vip_senders,
        sender_exclude=sender_exclude,
        max_candidates=max_candidates,
    )

    async def _pre_flight() -> None:
        candidates = pre_filter.stage1_candidates()
        if not candidates:
            extract_cell[0] = {}
            return
        extract_cell[0] = await fetch_extracts(api, reader, candidates)

    def _check_ref() -> HookResult:
        candidates = pre_filter.stage1_candidates()
        if not candidates:
            return HookResult.miss()
        boosted = pre_filter.stage2_boost(candidates)
        payload = pre_filter.build_payload(boosted, extract_cell[0])
        return HookResult.of(payload=payload, dedup_value=date.today().isoformat())

    hook = HookSpec(
        name="gmail_urgency_check",
        interval_seconds=interval_seconds,
        urgency="high",
        needs_llm=True,
        tier=1,
        dedup_key="gmail_urgency",
        check_ref=_check_ref,
        delivery=DeliverySpec(channel="ntfy", priority="high", tags=["mail", "urgent"]),
    )
    renderer = UrgencyTemplateRenderer()
    return (
        hook,
        _pre_flight,
        lambda registry: registry.register_template("gmail.gmail_urgency_check", renderer.render),
    )
