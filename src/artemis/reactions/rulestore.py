"""Reaction rule registry over Tier-A built-ins and M7 recipes.

Tier-A rules are the small day-one table of universal, internal, reversible,
zero-judgment reactions. The structural gate lives on ``ReactionRule`` itself:
Tier-A may never carry an external effect.

Tier-B rules are not stored in a separate reaction table. They are enabled M7
recipes whose ``task_class_key`` starts with ``reaction:`` and whose recipe text
declares the triggering event type. ``external_effect`` is derived from the
recipe action class so the dispatcher can route touching/taking recipes through
the owner gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from artemis.reactions.emit import EventType
from artemis.recipes import ActionClass, Promoter, Recipe, RecipeStatus, RecipeStore


class ReactionTier(StrEnum):
    """Reaction enablement tier."""

    A = "tier_a"
    B = "tier_b"


@dataclass(frozen=True)
class ReactionRule:
    """Event-to-reaction binding consumed by the reaction dispatcher."""

    name: str
    event_type: EventType
    tier: ReactionTier
    external_effect: bool
    reaction_ref: str
    dedup_key_fields: tuple[str, ...]
    stateful: bool = False

    def __post_init__(self) -> None:
        """Enforce the Tier-A gate structurally at registration time."""
        if self.tier == ReactionTier.A and self.external_effect:
            raise ValueError(
                f"Tier-A rule {self.name} may not have an external effect - "
                "it must graduate via Tier-B"
            )


TIER_A_BUILTINS: tuple[ReactionRule, ...] = (
    ReactionRule(
        "entity_link",
        EventType.FACT_ADDED,
        ReactionTier.A,
        False,
        "memory.resolve_entity",
        ("fact_id",),
    ),
    ReactionRule(
        "task_block_create",
        EventType.TASK_CREATED,
        ReactionTier.A,
        False,
        "tasks.schedule",
        ("task_id",),
    ),
    ReactionRule(
        "task_block_clear",
        EventType.TASK_DONE,
        ReactionTier.A,
        False,
        "tasks.schedule",
        ("task_id",),
        stateful=True,
    ),
    ReactionRule(
        "lifecycle_sync",
        EventType.EVENT_INGESTED,
        ReactionTier.A,
        False,
        "calendar.schedule_task",
        ("event_id",),
        stateful=True,
    ),
    ReactionRule(
        "bill_to_task",
        EventType.BILL_RECORDED,
        ReactionTier.A,
        False,
        "tasks.create_from_bill",
        ("bill_id",),
    ),
    ReactionRule(
        "cc_settlement_marker",
        EventType.PAYMENT_RECORDED,
        ReactionTier.A,
        False,
        "finance.mark_settlement",
        ("txn_id",),
        stateful=True,
    ),
    ReactionRule(
        "payment_bill_link",
        EventType.PAYMENT_RECORDED,
        ReactionTier.A,
        False,
        "finance.link_payment_bill",
        ("txn_id", "bill_id"),
        stateful=True,
    ),
    ReactionRule(
        "task_done_mark_paid",
        EventType.TASK_DONE,
        ReactionTier.A,
        False,
        "finance.mark_bill_paid",
        ("task_id",),
        stateful=True,
    ),
    ReactionRule(
        "date_fact",
        EventType.FACT_ADDED,
        ReactionTier.A,
        False,
        "memory.note_date_fact",
        ("fact_id",),
    ),
    ReactionRule(
        "gift_signal",
        EventType.FACT_ADDED,
        ReactionTier.A,
        False,
        "memory.note_gift_signal",
        ("fact_id",),
    ),
)


class ReactionRuleStore:
    """Resolve active reaction rules for a domain event type."""

    def __init__(
        self,
        recipe_store: RecipeStore,
        promoter: Promoter,
        *,
        builtins: tuple[ReactionRule, ...] = TIER_A_BUILTINS,
        disabled: frozenset[str] = frozenset(),
    ) -> None:
        self._recipe_store = recipe_store
        self._promoter = promoter
        self._builtins = builtins
        self._disabled = disabled

    def rules_for(self, event_type: EventType) -> list[ReactionRule]:
        """Return Tier-A built-ins plus ENABLED Tier-B reaction recipes."""
        rules = [
            rule
            for rule in self._builtins
            if rule.event_type == event_type and rule.name not in self._disabled
        ]
        rules.extend(
            rule
            for recipe in self._recipe_store.list(status=RecipeStatus.ENABLED)
            if (rule := self._rule_from_recipe(recipe, event_type)) is not None
            and rule.name not in self._disabled
        )
        return rules

    async def note_tier_b_occurrence(self, rule_name: str) -> None:
        """Delegate Tier-B recurrence accounting to the M7 promoter."""
        await self._promoter.note_occurrence(rule_name)

    def _rule_from_recipe(self, recipe: Recipe, event_type: EventType) -> ReactionRule | None:
        if not recipe.task_class_key.startswith("reaction:"):
            return None
        if _recipe_event_type(recipe) != event_type:
            return None
        external_effect = recipe.action_class in {
            ActionClass.TOUCHES_DATA,
            ActionClass.TAKES_ACTION,
        }
        return ReactionRule(
            name=recipe.task_class_key,
            event_type=event_type,
            tier=ReactionTier.B,
            external_effect=external_effect,
            reaction_ref=recipe.task_class_key,
            dedup_key_fields=("dedup_key",),
        )


def _recipe_event_type(recipe: Recipe) -> EventType | None:
    text = f"{recipe.description}\n{recipe.instructions}".lower()
    for event_type in EventType:
        if event_type.value in text or event_type.name.lower() in text:
            return event_type
    return None
