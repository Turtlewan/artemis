"""Curiosity loop public API and Heartbeat hook helper."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from artemis.curiosity.gaps import (
    ConfidenceEvent,
    EscalationEvent,
    Gap,
    StaleItem,
    TelemetrySource,
    pick_top_gap,
    scan_gaps,
)
from artemis.curiosity.loop import CuriosityLoop, StagedItem, StagingStore, TokenLedger
from artemis.curiosity.research import (
    GroundingError,
    HttpReachability,
    Reachability,
    Researcher,
    ResearchResult,
    Source,
    StubResearcher,
    grounding_gate,
    registrable_domain,
)


def make_curiosity_hook(
    loop: CuriosityLoop,
    is_idle: Callable[[], bool],
) -> Callable[[], Awaitable[str]]:
    """Return the async callable mounted by Heartbeat for idle Curiosity ticks."""

    async def hook() -> str:
        return await loop.curiosity_tick(is_idle=is_idle, now=datetime.now(tz=UTC))

    return hook


__all__ = [
    "ConfidenceEvent",
    "CuriosityLoop",
    "EscalationEvent",
    "Gap",
    "GroundingError",
    "HttpReachability",
    "Reachability",
    "ResearchResult",
    "Researcher",
    "Source",
    "StagedItem",
    "StagingStore",
    "StaleItem",
    "StubResearcher",
    "TelemetrySource",
    "TokenLedger",
    "grounding_gate",
    "make_curiosity_hook",
    "pick_top_gap",
    "registrable_domain",
    "scan_gaps",
]
