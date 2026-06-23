"""Value types for proactive hook dispatch.

M6-a only carries deterministic hook results through the heartbeat scheduler.
It does not call an LLM, notification transport, broker, or durable queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Self

from pydantic import BaseModel, Field

HEARTBEAT_OK: Final[str] = "HEARTBEAT_OK"
"""Silent-success sentinel: the heartbeat tick produced no hits."""


class HookResult(BaseModel):
    """Deterministic result returned by a proactive hook check."""

    hit: bool
    payload: dict[str, object] = Field(default_factory=dict)
    dedup_value: str | None = None

    @classmethod
    def miss(cls) -> Self:
        """Return a no-hit result."""
        return cls(hit=False)

    @classmethod
    def of(cls, payload: dict[str, object], *, dedup_value: str | None = None) -> Self:
        """Return a hit result with structured payload."""
        return cls(hit=True, payload=payload, dedup_value=dedup_value)


class DeliverySpec(BaseModel):
    """Shape-only ntfy delivery descriptor consumed by later milestones."""

    channel: Literal["ntfy"] = "ntfy"
    priority: Literal["min", "low", "default", "high", "max"] | None = None
    tags: list[str] = Field(default_factory=list)
    click_url: str | None = None
    actions: list[dict[str, str]] = Field(default_factory=list)


@dataclass(frozen=True)
class Hit:
    """One resolved hook firing carried to the later hit-handling seam."""

    module: str
    hook_name: str
    tier: Literal[0, 1]
    urgency: Literal["low", "normal", "high"]
    needs_llm: bool
    dedup_key: str | None
    result: HookResult
    delivery: DeliverySpec | None


@dataclass(frozen=True)
class TickResult(str):
    """Heartbeat tick result.

    The ``str`` base preserves M1-d compatibility for callers that compared
    ``Heartbeat().tick()`` directly to ``HEARTBEAT_OK``.
    """

    hits: tuple[Hit, ...]
    summary: str
    tier1_skipped: tuple[str, ...]

    def __new__(cls, hits: tuple[Hit, ...], summary: str, tier1_skipped: tuple[str, ...]) -> Self:
        return str.__new__(cls, summary)

    @property
    def is_silent_success(self) -> bool:
        """Return true when the tick produced no hits."""
        return len(self.hits) == 0
