"""Rule-based recipe dedupe and retirement.

``dedupe_retire`` applies three deterministic rules without a generative model call:
exact duplicates retire the lower version, near duplicates retire the older verified recipe,
and superseded task versions retire lower versions. When a retirement criterion ties, the
lower parsed version and then lower lexicographic name loses.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from artemis.ports.types import Vector
from artemis.recipes.model import Recipe, RecipeStatus
from artemis.recipes.store import RecipeStore

type _RecipeKey = tuple[str, str]


async def dedupe_retire(
    store: RecipeStore,
    *,
    similarity_threshold: float = 0.92,
) -> list[str]:
    """Retire duplicate or superseded recipes and return retired recipe names.

    Rules:
    - exact-dupe: same task class key and canonical instructions retire the lower version.
    - near-dupe: enabled recipes with similar descriptions and the same action class retire
      the older ``verified_at`` recipe.
    - superseded: a higher parsed version for a task class retires lower versions.

    Ties retire the lower parsed version, then the lower lexicographic name, so results do not
    depend on ``RecipeStore.list()`` or filesystem iteration order.
    """
    recipes = _all_recipes(store)
    retirements: dict[_RecipeKey, Recipe] = {}

    for group in _groups(recipes, key=lambda recipe: (recipe.task_class_key, _canonical(recipe))):
        if len(group) < 2:
            continue
        winner = max(group, key=_version_name_rank)
        for recipe in group:
            if recipe != winner:
                retirements[(recipe.name, recipe.version)] = recipe

    for group in _groups(recipes, key=lambda recipe: recipe.task_class_key):
        if len(group) < 2:
            continue
        max_version = max(_version_tuple(recipe.version) for recipe in group)
        for recipe in group:
            if _version_tuple(recipe.version) < max_version:
                retirements[(recipe.name, recipe.version)] = recipe

    enabled = [recipe for recipe in recipes if recipe.status == RecipeStatus.ENABLED]
    vectors = await _description_vectors(store, enabled)
    for left_index, left in enumerate(enabled):
        for right_index in range(left_index + 1, len(enabled)):
            right = enabled[right_index]
            if left.action_class != right.action_class:
                continue
            if _cosine(vectors[left_index], vectors[right_index]) < similarity_threshold:
                continue
            loser = _near_dupe_loser(left, right)
            retirements[(loser.name, loser.version)] = loser

    retired_names: list[str] = []
    for name, version in sorted(retirements):
        await store.set_status(name, RecipeStatus.RETIRED, version=version)
        retired_names.append(name)
    return retired_names


def _all_recipes(store: RecipeStore) -> list[Recipe]:
    recipes: list[Recipe] = []
    for path in store._recipes_dir.glob("*.skill.md"):
        stem = path.name
        if "@" not in stem or not stem.endswith(".skill.md"):
            continue
        name, version_suffix = stem.removesuffix(".skill.md").split("@", 1)
        recipes.append(store.get(name, version=version_suffix))
    return sorted(recipes, key=lambda recipe: (recipe.name, _version_tuple(recipe.version)))


def _groups[T](items: Sequence[T], *, key: Callable[[T], object]) -> list[list[T]]:
    grouped: dict[object, list[T]] = {}
    for item in items:
        grouped.setdefault(key(item), []).append(item)
    return list(grouped.values())


def _canonical(recipe: Recipe) -> str:
    return " ".join(recipe.instructions.split())


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _version_name_rank(recipe: Recipe) -> tuple[tuple[int, ...], str]:
    return (_version_tuple(recipe.version), recipe.name)


async def _description_vectors(store: RecipeStore, recipes: Sequence[Recipe]) -> list[Vector]:
    if not recipes:
        return []
    return await store._embedder.embed_documents([recipe.description for recipe in recipes])


def _cosine(left: Vector, right: Vector) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right)) / (
        left_norm * right_norm
    )


def _near_dupe_loser(left: Recipe, right: Recipe) -> Recipe:
    left_verified = left.provenance.get("verified_at", "")
    right_verified = right.provenance.get("verified_at", "")
    if left_verified != right_verified:
        return left if left_verified < right_verified else right
    return min(left, right, key=_version_name_rank)
