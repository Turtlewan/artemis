from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from artemis.ports.types import Vector
from artemis.recipes import (
    ActionClass,
    Recipe,
    RecipeClass,
    RecipeSigner,
    RecipeStatus,
    RecipeStore,
    dedupe_retire,
)


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 8

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._embed(query)

    def _embed(self, text: str) -> Vector:
        tokens = {token.strip(".,").lower() for token in text.split()}
        values = [0.0] * self.dimension
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            values[digest[0] % self.dimension] += 1.0
        return values


class FakeKeyProvider:
    def signing_key(self) -> bytes:
        return b"test-recipe-dedupe-signing-key"


def _store(tmp_path: Path) -> RecipeStore:
    return RecipeStore(
        FakeEmbedder(),
        tmp_path / "recipes",
        signer=RecipeSigner(FakeKeyProvider()),
    )


def _recipe(
    name: str,
    *,
    description: str = "calendar focus planning",
    version: str = "0.1.0",
    action_class: ActionClass = ActionClass.READ_ONLY,
    task_class_key: str = "calendar.focus",
    instructions: str = "Follow the deterministic recipe.",
    status: RecipeStatus = RecipeStatus.ENABLED,
    verified_at: str = "2026-01-01T00:00:00Z",
) -> Recipe:
    return Recipe(
        name=name,
        description=description,
        version=version,
        recipe_class=RecipeClass.INSTRUCTIONS,
        action_class=action_class,
        task_class_key=task_class_key,
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        instructions=instructions,
        status=status,
        provenance={"source": "test", "verified_at": verified_at},
    )


async def test_exact_dupe_retires_lower_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = _recipe(
        "exact_old",
        version="0.1.0",
        instructions="Follow   the\nsame recipe.",
        task_class_key="exact.task",
    )
    survivor = _recipe(
        "exact_new",
        version="0.2.0",
        instructions="Follow the same recipe.",
        task_class_key="exact.task",
    )

    await store.write(survivor)
    await store.write(old)

    assert await dedupe_retire(store) == ["exact_old"]
    assert store.get("exact_old", version="0.1.0").status == RecipeStatus.RETIRED
    assert store.get("exact_new", version="0.2.0").status == RecipeStatus.ENABLED


async def test_near_dupe_retires_older_verified_recipe(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = _recipe(
        "near_old",
        description="daily planning checklist",
        task_class_key="near.old",
        verified_at="2026-01-01T00:00:00Z",
    )
    new = _recipe(
        "near_new",
        description="daily planning checklist",
        task_class_key="near.new",
        verified_at="2026-02-01T00:00:00Z",
    )

    await store.write(new)
    await store.write(old)

    assert await dedupe_retire(store) == ["near_old"]
    assert store.get("near_old").status == RecipeStatus.RETIRED
    assert store.get("near_new").status == RecipeStatus.ENABLED


async def test_superseded_retires_lower_named_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = _recipe(
        "foo",
        version="0.1.0",
        task_class_key="foo.task",
        instructions="Use the old recipe.",
    )
    new = _recipe(
        "foo",
        version="0.2.0",
        task_class_key="foo.task",
        instructions="Use the new recipe.",
    )

    await store.write(new)
    await store.write(old)

    assert await dedupe_retire(store) == ["foo"]
    assert store.get("foo", version="0.1.0").status == RecipeStatus.RETIRED
    assert store.get("foo", version="0.2.0").status == RecipeStatus.ENABLED


async def test_near_dupe_tiebreaker_is_deterministic_across_insertion_order(
    tmp_path: Path,
) -> None:
    first = await _run_tiebreaker(tmp_path / "first", reverse=False)
    second = await _run_tiebreaker(tmp_path / "second", reverse=True)

    assert first == ["alpha"]
    assert second == ["alpha"]


async def _run_tiebreaker(path: Path, *, reverse: bool) -> list[str]:
    store = _store(path)
    alpha = _recipe(
        "alpha",
        description="shared duplicate work",
        task_class_key="alpha.task",
        instructions="Run alpha.",
        verified_at="2026-01-01T00:00:00Z",
    )
    beta = _recipe(
        "beta",
        description="shared duplicate work",
        task_class_key="beta.task",
        instructions="Run beta.",
        verified_at="2026-01-01T00:00:00Z",
    )
    recipes = [beta, alpha] if reverse else [alpha, beta]
    for recipe in recipes:
        await store.write(recipe)

    retired = await dedupe_retire(store)

    assert store.get("alpha").status == RecipeStatus.RETIRED
    assert store.get("beta").status == RecipeStatus.ENABLED
    return retired
