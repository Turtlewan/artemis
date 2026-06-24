"""Recipe promotion policy and recurrence counter.

This module encodes the #8 auto-enable-safe vs gated boundary. Only
``READ_ONLY`` and ``NO_DATA`` recipes can be auto-enabled by recurrence;
recipes that touch data or take actions are moved to owner review instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, cast

from artemis.config import Settings
from artemis.recipes.model import ActionClass, Recipe, RecipeStatus
from artemis.recipes.store import RecipeStore, recipes_dir

RecipeSafety = Literal["auto-enable", "gated"]


class RecipeAlreadyRetiredError(Exception):
    """Raised when an owner command tries to promote a retired recipe."""


def recurrence_path(s: Settings) -> Path:
    """Return the persisted recurrence counter path for a settings slot."""
    return recipes_dir(s) / "recurrence.json"


def classify_safety(recipe: Recipe) -> RecipeSafety:
    """Classify whether a recipe may auto-enable or must be owner-gated."""
    if recipe.action_class in {ActionClass.READ_ONLY, ActionClass.NO_DATA}:
        return "auto-enable"
    return "gated"


class RecurrenceStore:
    """Small JSON store for recurrence counts keyed by task class.

    The heartbeat is single-process/single-threaded; a hypothetical concurrent
    lost increment would only delay promotion, not bypass the threshold.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._counts = self._load()

    def note(self, task_class_key: str) -> int:
        """Increment and persist the count for ``task_class_key``."""
        count = self.count(task_class_key) + 1
        self._counts[task_class_key] = count
        self._persist()
        return count

    def count(self, task_class_key: str) -> int:
        """Return the current count for ``task_class_key``."""
        return self._counts.get(task_class_key, 0)

    def reset(self, task_class_key: str) -> None:
        """Clear the recurrence count for ``task_class_key``."""
        self._counts.pop(task_class_key, None)
        self._persist()

    def _load(self) -> dict[str, int]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}

        counts: dict[str, int] = {}
        for key, value in cast(dict[object, object], raw).items():
            if isinstance(key, str) and isinstance(value, int) and value >= 0:
                counts[key] = value
        return counts

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.tmp")
        temp.write_text(json.dumps(self._counts, sort_keys=True), encoding="utf-8")
        os.replace(temp, self.path)


class Promoter:
    """Promote recipes by recurrence threshold or explicit owner command."""

    def __init__(self, store: RecipeStore, recurrence: RecurrenceStore, threshold: int = 2) -> None:
        self.store = store
        self.recurrence = recurrence
        self.threshold = threshold

    async def note_occurrence(self, task_class_key: str) -> None:
        """Record a repeated task class and promote a matching candidate at threshold."""
        candidates = [
            recipe
            for recipe in self.store.list(status=RecipeStatus.CANDIDATE)
            if recipe.task_class_key == task_class_key
        ]
        if not candidates:
            return

        count = self.recurrence.note(task_class_key)
        if count >= self.threshold:
            await self._auto_promote(candidates[0])

    async def _auto_promote(self, recipe: Recipe) -> None:
        """Auto-enable clearly-safe recipes; move gated recipes to owner review."""
        if recipe.status in {RecipeStatus.ENABLED, RecipeStatus.PENDING}:
            return
        if classify_safety(recipe) == "auto-enable":
            await self.store.set_status(recipe.name, RecipeStatus.ENABLED)
            return
        await self.store.set_status(recipe.name, RecipeStatus.PENDING)

    async def promote(self, name: str) -> Recipe:
        """Owner command: verify and enable a non-retired recipe."""
        recipe = self.store.get(name)
        if recipe.status == RecipeStatus.RETIRED:
            raise RecipeAlreadyRetiredError(name)
        await self.store.set_status(name, RecipeStatus.ENABLED)
        return recipe.model_copy(update={"status": RecipeStatus.ENABLED})

    async def reject(self, name: str) -> Recipe:
        """Owner command: retire a recipe."""
        recipe = self.store.get(name)
        await self.store.set_status(name, RecipeStatus.RETIRED)
        return recipe.model_copy(update={"status": RecipeStatus.RETIRED})
