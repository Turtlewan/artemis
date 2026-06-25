from __future__ import annotations

from typing import cast

import pytest

from artemis.reactions import EventType, ReactionRule, ReactionRuleStore, ReactionTier
from artemis.reactions.rulestore import TIER_A_BUILTINS
from artemis.recipes import ActionClass, Promoter, Recipe, RecipeClass, RecipeStatus, RecipeStore


class FakeRecipeStore:
    def __init__(self) -> None:
        self.recipes: dict[str, Recipe] = {}

    async def write(self, recipe: Recipe) -> None:
        self.recipes[recipe.name] = recipe.model_copy(deep=True)

    def list(self, *, status: RecipeStatus | None = None) -> list[Recipe]:
        values = list(self.recipes.values())
        if status is None:
            return values
        return [recipe for recipe in values if recipe.status == status]

    def get(self, name: str, version: str | None = None) -> Recipe:
        del version
        return self.recipes[name]

    async def set_status(
        self,
        name: str,
        status: RecipeStatus,
        *,
        version: str | None = None,
    ) -> None:
        del version
        recipe = self.recipes[name]
        self.recipes[name] = recipe.model_copy(update={"status": status})


class FakePromoter:
    def __init__(self) -> None:
        self.occurrences: list[str] = []

    async def note_occurrence(self, task_class_key: str) -> None:
        self.occurrences.append(task_class_key)


def _recipe(
    *,
    name: str = "gift_followup",
    task_class_key: str = "reaction:gift_followup",
    event_type: EventType = EventType.FACT_ADDED,
    action_class: ActionClass = ActionClass.TOUCHES_DATA,
    status: RecipeStatus = RecipeStatus.ENABLED,
) -> Recipe:
    return Recipe(
        name=name,
        description=f"Reaction recipe for event_type: {event_type.value}",
        version="0.1.0",
        recipe_class=RecipeClass.INSTRUCTIONS,
        action_class=action_class,
        task_class_key=task_class_key,
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        instructions=f"Run when event_type: {event_type.value}.",
        status=status,
        provenance={"source": "test"},
    )


def _store(
    recipe_store: FakeRecipeStore | None = None,
    promoter: FakePromoter | None = None,
    *,
    disabled: frozenset[str] = frozenset(),
) -> tuple[ReactionRuleStore, FakeRecipeStore, FakePromoter]:
    recipes = recipe_store or FakeRecipeStore()
    rule_promoter = promoter or FakePromoter()
    return (
        ReactionRuleStore(
            cast(RecipeStore, recipes),
            cast(Promoter, rule_promoter),
            disabled=disabled,
        ),
        recipes,
        rule_promoter,
    )


def test_tier_a_external_effect_rejected() -> None:
    with pytest.raises(ValueError, match="may not have an external effect"):
        ReactionRule(
            "x",
            EventType.TASK_DONE,
            ReactionTier.A,
            external_effect=True,
            reaction_ref="tasks.external",
            dedup_key_fields=("task_id",),
        )

    assert ReactionRule(
        "internal",
        EventType.TASK_DONE,
        ReactionTier.A,
        external_effect=False,
        reaction_ref="tasks.internal",
        dedup_key_fields=("task_id",),
    )
    assert ReactionRule(
        "reaction:gated",
        EventType.TASK_DONE,
        ReactionTier.B,
        external_effect=True,
        reaction_ref="reaction:gated",
        dedup_key_fields=("task_id",),
    )


def test_builtin_table_integrity() -> None:
    assert len(TIER_A_BUILTINS) == 10
    assert all(rule.tier == ReactionTier.A for rule in TIER_A_BUILTINS)
    assert all(not rule.external_effect for rule in TIER_A_BUILTINS)
    assert len({rule.name for rule in TIER_A_BUILTINS}) == len(TIER_A_BUILTINS)
    assert all(isinstance(rule.event_type, EventType) for rule in TIER_A_BUILTINS)


def test_rules_for_tier_a_by_event_type() -> None:
    rule_store, _, _ = _store()

    bill_rules = rule_store.rules_for(EventType.BILL_RECORDED)
    task_done_rules = rule_store.rules_for(EventType.TASK_DONE)

    assert "bill_to_task" in {rule.name for rule in bill_rules}
    assert {"task_block_clear", "task_done_mark_paid"} <= {rule.name for rule in task_done_rules}


async def test_rules_for_tier_b_via_recipe_store() -> None:
    rule_store, recipe_store, _ = _store()
    await recipe_store.write(_recipe())

    fact_rules = rule_store.rules_for(EventType.FACT_ADDED)
    tier_b = [
        rule
        for rule in fact_rules
        if rule.name == "reaction:gift_followup" and rule.tier == ReactionTier.B
    ]

    assert len(tier_b) == 1
    assert tier_b[0].reaction_ref == "reaction:gift_followup"
    assert tier_b[0].external_effect is True


async def test_rules_for_ignores_non_matching_and_non_enabled_recipes() -> None:
    rule_store, recipe_store, _ = _store()
    await recipe_store.write(_recipe(name="candidate", status=RecipeStatus.CANDIDATE))
    await recipe_store.write(
        _recipe(
            name="other_event",
            task_class_key="reaction:other_event",
            event_type=EventType.TASK_DONE,
        )
    )
    await recipe_store.write(
        _recipe(name="plain", task_class_key="plain.task", event_type=EventType.FACT_ADDED)
    )

    fact_rule_names = {rule.name for rule in rule_store.rules_for(EventType.FACT_ADDED)}

    assert "reaction:gift_followup" not in fact_rule_names
    assert "reaction:other_event" not in fact_rule_names
    assert "plain.task" not in fact_rule_names


def test_owner_disable_excludes_rule() -> None:
    rule_store, _, _ = _store(disabled=frozenset({"bill_to_task"}))

    assert "bill_to_task" not in {
        rule.name for rule in rule_store.rules_for(EventType.BILL_RECORDED)
    }


async def test_graduation_seam_delegates_to_promoter() -> None:
    rule_store, _, promoter = _store()

    await rule_store.note_tier_b_occurrence("reaction:gift_followup")

    assert promoter.occurrences == ["reaction:gift_followup"]
