"""Reaction event emit and dispatcher package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artemis.reactions.dispatcher import ReactionDispatcher
    from artemis.reactions.emit import DomainEvent, EventBus, EventType
    from artemis.reactions.ledger import ReactionLedger
    from artemis.reactions.rulestore import (
        TIER_A_BUILTINS,
        ReactionRule,
        ReactionRuleStore,
        ReactionTier,
    )

__all__ = [
    "DomainEvent",
    "EventBus",
    "EventType",
    "ReactionDispatcher",
    "ReactionLedger",
    "ReactionRule",
    "ReactionRuleStore",
    "ReactionTier",
    "TIER_A_BUILTINS",
]


def __getattr__(name: str) -> object:
    if name in {"DomainEvent", "EventBus", "EventType"}:
        from artemis.reactions import emit

        return getattr(emit, name)
    if name == "ReactionDispatcher":
        from artemis.reactions.dispatcher import ReactionDispatcher

        return ReactionDispatcher
    if name == "ReactionLedger":
        from artemis.reactions.ledger import ReactionLedger

        return ReactionLedger
    if name in {"ReactionRule", "ReactionRuleStore", "ReactionTier", "TIER_A_BUILTINS"}:
        from artemis.reactions import rulestore

        return getattr(rulestore, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
