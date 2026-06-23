from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest

from artemis.ports.retrieval import VectorStore
from artemis.ports.types import Vector
from artemis.recipes import (
    ActionClass,
    Recipe,
    RecipeClass,
    RecipeIndex,
    RecipeSignatureError,
    RecipeSigner,
    RecipeStatus,
    RecipeStore,
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
        return b"test-recipe-signing-key"


def sample_recipe(
    name: str = "alpha",
    description: str = "organize calendar focus blocks",
    *,
    version: str = "0.1.0",
    status: RecipeStatus = RecipeStatus.CANDIDATE,
) -> Recipe:
    return Recipe(
        name=name,
        description=description,
        version=version,
        recipe_class=RecipeClass.INSTRUCTIONS,
        action_class=ActionClass.READ_ONLY,
        task_class_key="calendar.focus",
        inputs_schema={"type": "object", "properties": {"topic": {"type": "string"}}},
        outputs_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        instructions="Use the calendar context to identify useful focus blocks.",
        script="print('focus')",
        status=status,
        provenance={"source": "test"},
    )


def test_recipe_skill_md_round_trip_is_lossless() -> None:
    recipe = sample_recipe()

    assert Recipe.from_skill_md(recipe.to_skill_md()) == recipe


def test_sign_verify_and_post_round_trip_verify() -> None:
    signer = RecipeSigner(FakeKeyProvider())
    recipe = sample_recipe()
    recipe.signature = signer.sign(recipe)

    assert signer.verify(recipe)
    assert signer.verify(Recipe.from_skill_md(recipe.to_skill_md()))

    tampered = recipe.model_copy(update={"description": "different description"})
    assert not signer.verify(tampered)


async def test_store_retrieves_enabled_recipes_only(tmp_path: Path) -> None:
    store = RecipeStore(FakeEmbedder(), tmp_path, signer=RecipeSigner(FakeKeyProvider()))
    alpha = sample_recipe(
        name="alpha",
        description="calendar focus planning deep work",
        status=RecipeStatus.ENABLED,
    )
    beta = sample_recipe(
        name="beta",
        description="finance ledger recurring reconciliation",
        status=RecipeStatus.ENABLED,
    )
    candidate = sample_recipe(
        name="gamma",
        description="calendar focus planning candidate",
        status=RecipeStatus.CANDIDATE,
    )

    await store.write(alpha)
    await store.write(beta)
    await store.write(candidate)

    assert await store.retrieve_recipes("calendar focus", k=1) == ["alpha"]
    assert "gamma" not in await store.retrieve_recipes("calendar focus", k=3)


async def test_set_status_upserts_index_and_excludes_retired(tmp_path: Path) -> None:
    store = RecipeStore(FakeEmbedder(), tmp_path, signer=RecipeSigner(FakeKeyProvider()))
    recipe = sample_recipe(status=RecipeStatus.ENABLED)

    await store.write(recipe)
    await store.set_status(recipe.name, RecipeStatus.RETIRED)

    assert recipe.name not in await store.retrieve_recipes(recipe.description, k=3)


async def test_numeric_version_order_and_tampered_set_status_refusal(tmp_path: Path) -> None:
    store = RecipeStore(FakeEmbedder(), tmp_path, signer=RecipeSigner(FakeKeyProvider()))
    old = sample_recipe(version="0.9.0", status=RecipeStatus.ENABLED)
    new = sample_recipe(version="0.10.0", status=RecipeStatus.ENABLED)

    await store.write(old)
    await store.write(new)

    assert store.get("alpha").version == "0.10.0"

    path = tmp_path / "alpha@0.10.0.skill.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("organize", "tampered"), encoding="utf-8"
    )

    with pytest.raises(RecipeSignatureError):
        await store.set_status("alpha", RecipeStatus.RETIRED)


def test_recipe_index_conforms_to_vector_store_port() -> None:
    _check: VectorStore = RecipeIndex()
    assert _check.search("recipes", [1.0], 1) == []
