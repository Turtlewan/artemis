"""Owner review surface for promoted recipes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from artemis.recipes.model import ActionClass, Recipe, RecipeStatus
from artemis.recipes.promotion import Promoter, classify_safety
from artemis.recipes.store import RecipeStore


@dataclass(frozen=True)
class RecipeReview:
    """Plain data returned to owner-facing review clients."""

    name: str
    description: str
    status: str
    action_class: str
    safety: Literal["auto-enable", "gated"]
    explanation: str


def explain(recipe: Recipe) -> str:
    """Return a deterministic plain-language explanation with no model call."""
    safety = classify_safety(recipe)
    action_text = {
        ActionClass.NO_DATA: "reads no personal data",
        ActionClass.READ_ONLY: "only reads data, never changes it",
        ActionClass.TOUCHES_DATA: "reads or writes your data",
        ActionClass.TAKES_ACTION: "takes actions on your behalf",
    }[recipe.action_class]
    safety_text = (
        "auto-enabled because it is clearly safe"
        if safety == "auto-enable"
        else "kept pending your approval because it touches data or takes actions"
    )
    return (
        f"'{recipe.name}': {recipe.description}. This recipe {action_text}. It was {safety_text}."
    )


class ReviewSurface:
    """Owner-facing API for auto-enabled and pending recipe review."""

    def __init__(self, store: RecipeStore, promoter: Promoter) -> None:
        self.store = store
        self.promoter = promoter

    def auto_enabled(self) -> list[RecipeReview]:
        """List enabled recipes that reached enabled state through the safe class."""
        return [
            self._review(recipe)
            for recipe in self.store.list(status=RecipeStatus.ENABLED)
            if classify_safety(recipe) == "auto-enable"
        ]

    def pending_for_review(self) -> list[RecipeReview]:
        """List recipes awaiting explicit owner approval."""
        return [self._review(recipe) for recipe in self.store.list(status=RecipeStatus.PENDING)]

    async def approve(self, name: str) -> RecipeReview:
        """Approve a pending recipe and return its enabled review."""
        recipe = await self.promoter.promote(name)
        return self._review(recipe)

    async def reject(self, name: str) -> RecipeReview:
        """Reject a recipe and return its retired review."""
        recipe = await self.promoter.reject(name)
        return self._review(recipe)

    def _review(self, recipe: Recipe) -> RecipeReview:
        return RecipeReview(
            name=recipe.name,
            description=recipe.description,
            status=recipe.status.value,
            action_class=recipe.action_class.value,
            safety=classify_safety(recipe),
            explanation=explain(recipe),
        )
