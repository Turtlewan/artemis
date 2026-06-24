from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import cast

import pytest

from artemis.brain import Brain
from artemis.ports.model import ModelResponse
from artemis.ports.routing import RouteDecision
from artemis.ports.types import Message, Scope, Vector
from artemis.recipes import (
    ActionClass,
    Promoter,
    Recipe,
    RecipeAlreadyRetiredError,
    RecipeClass,
    RecipeSignatureError,
    RecipeSigner,
    RecipeStatus,
    RecipeStore,
    RecurrenceStore,
    ReviewSurface,
    classify_safety,
    explain,
)
from artemis.registry import ToolRegistry
from artemis.router import SemanticRouter


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
        return b"test-recipe-promotion-signing-key"


class FakeRouter:
    def __init__(self, decision: RouteDecision) -> None:
        self._decision = decision

    async def route(self, request_text: str, scope: Scope) -> RouteDecision:
        del request_text, scope
        return self._decision


class FakeModel:
    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, messages, response_schema, temperature, max_tokens
        return ModelResponse(text=json.dumps({"ok": True}))

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature

        async def _gen() -> AsyncIterator[str]:
            yield "chunk"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


def _recipe(
    name: str,
    action_class: ActionClass,
    *,
    status: RecipeStatus = RecipeStatus.CANDIDATE,
    task_class_key: str = "calendar.focus",
) -> Recipe:
    return Recipe(
        name=name,
        description=f"{name} recipe description",
        version="0.1.0",
        recipe_class=RecipeClass.INSTRUCTIONS,
        action_class=action_class,
        task_class_key=task_class_key,
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        instructions="Follow the deterministic recipe.",
        status=status,
        provenance={"source": "test"},
    )


def _store(tmp_path: Path) -> RecipeStore:
    return RecipeStore(
        FakeEmbedder(),
        tmp_path / "recipes",
        signer=RecipeSigner(FakeKeyProvider()),
    )


def _promoter(tmp_path: Path, store: RecipeStore, *, threshold: int = 2) -> Promoter:
    return Promoter(store, RecurrenceStore(tmp_path / "recurrence.json"), threshold=threshold)


def test_classification_and_recurrence_store_persistence(tmp_path: Path) -> None:
    assert classify_safety(_recipe("read_recipe", ActionClass.READ_ONLY)) == "auto-enable"
    assert classify_safety(_recipe("nodata_recipe", ActionClass.NO_DATA)) == "auto-enable"
    assert classify_safety(_recipe("touch_recipe", ActionClass.TOUCHES_DATA)) == "gated"
    assert classify_safety(_recipe("action_recipe", ActionClass.TAKES_ACTION)) == "gated"

    path = tmp_path / "recurrence.json"
    recurrence = RecurrenceStore(path)
    assert recurrence.note("calendar.focus") == 1
    assert RecurrenceStore(path).count("calendar.focus") == 1
    path.write_text("{bad json", encoding="utf-8")
    assert RecurrenceStore(path).count("calendar.focus") == 0


async def test_recurrence_auto_enables_safe_candidate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recipe = _recipe("safe_recipe", ActionClass.READ_ONLY)
    promoter = _promoter(tmp_path, store)

    await store.write(recipe)
    await promoter.note_occurrence(recipe.task_class_key)
    await promoter.note_occurrence(recipe.task_class_key)

    assert store.get(recipe.name).status == RecipeStatus.ENABLED


async def test_recurrence_gates_data_recipe_for_review(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recipe = _recipe("data_recipe", ActionClass.TOUCHES_DATA)
    promoter = _promoter(tmp_path, store)
    review = ReviewSurface(store, promoter)

    await store.write(recipe)
    await promoter.note_occurrence(recipe.task_class_key)
    await promoter.note_occurrence(recipe.task_class_key)

    assert store.get(recipe.name).status == RecipeStatus.PENDING
    assert [item.name for item in review.pending_for_review()] == [recipe.name]


async def test_recurrence_below_threshold_leaves_candidate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recipe = _recipe("below_recipe", ActionClass.READ_ONLY)
    promoter = _promoter(tmp_path, store)

    await store.write(recipe)
    await promoter.note_occurrence(recipe.task_class_key)

    assert store.get(recipe.name).status == RecipeStatus.CANDIDATE


async def test_owner_command_override_enables_gated_recipe(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recipe = _recipe("owner_recipe", ActionClass.TAKES_ACTION)
    promoter = _promoter(tmp_path, store)

    await store.write(recipe)
    promoted = await promoter.promote(recipe.name)

    assert promoted.status == RecipeStatus.ENABLED
    assert store.get(recipe.name).status == RecipeStatus.ENABLED


async def test_review_surface_lists_explains_approves_and_rejects(tmp_path: Path) -> None:
    store = _store(tmp_path)
    promoter = _promoter(tmp_path, store)
    review = ReviewSurface(store, promoter)
    safe = _recipe("enabled_safe", ActionClass.NO_DATA, status=RecipeStatus.ENABLED)
    pending = _recipe(
        "pending_data",
        ActionClass.TOUCHES_DATA,
        status=RecipeStatus.PENDING,
        task_class_key="data.task",
    )
    rejected = _recipe(
        "pending_action",
        ActionClass.TAKES_ACTION,
        status=RecipeStatus.PENDING,
        task_class_key="action.task",
    )

    await store.write(safe)
    await store.write(pending)
    await store.write(rejected)

    auto_enabled = review.auto_enabled()
    assert [item.name for item in auto_enabled] == [safe.name]
    assert auto_enabled[0].explanation

    pending_names = [item.name for item in review.pending_for_review()]
    assert pending_names == [rejected.name, pending.name]

    approved_review = await review.approve(pending.name)
    assert approved_review.status == RecipeStatus.ENABLED.value
    assert store.get(pending.name).status == RecipeStatus.ENABLED
    assert pending.name not in [item.name for item in review.pending_for_review()]

    rejected_review = await review.reject(rejected.name)
    assert rejected_review.status == RecipeStatus.RETIRED.value
    assert store.get(rejected.name).status == RecipeStatus.RETIRED


def test_explanation_coverage_all_action_classes() -> None:
    explanations = {
        action_class: explain(_recipe(f"recipe_{index}", action_class))
        for index, action_class in enumerate(ActionClass)
    }

    assert all(explanations.values())
    assert len(set(explanations.values())) == len(ActionClass)


async def test_brain_promoter_wiring_notes_escalation_occurrences(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recipe = _recipe("brain_recipe", ActionClass.READ_ONLY, task_class_key="brain.task")
    promoter = _promoter(tmp_path, store)
    brain = Brain(
        cast(
            SemanticRouter,
            FakeRouter(
                RouteDecision(path="escalate", candidate_tools=["brain.task"], confidence=0.1)
            ),
        ),
        ToolRegistry(FakeEmbedder()),
        FakeModel(),
        store=store,
        promoter=promoter,
    )

    await store.write(recipe)
    await brain.respond("hard repeated task", "owner-private")
    await brain.respond("hard repeated task", "owner-private")

    assert store.get(recipe.name).status == RecipeStatus.ENABLED


async def test_brain_without_promoter_leaves_candidate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recipe = _recipe("plain_brain", ActionClass.READ_ONLY, task_class_key="brain.task")
    brain = Brain(
        cast(
            SemanticRouter,
            FakeRouter(
                RouteDecision(path="escalate", candidate_tools=["brain.task"], confidence=0.1)
            ),
        ),
        ToolRegistry(FakeEmbedder()),
        FakeModel(),
        store=store,
        promoter=None,
    )

    await store.write(recipe)
    await brain.respond("hard repeated task", "owner-private")
    await brain.respond("hard repeated task", "owner-private")

    assert store.get(recipe.name).status == RecipeStatus.CANDIDATE


async def test_promote_bad_signature_and_retired_recipe_errors(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bad_signature = _recipe("tampered_recipe", ActionClass.READ_ONLY)
    retired = _recipe(
        "retired_recipe",
        ActionClass.READ_ONLY,
        status=RecipeStatus.RETIRED,
        task_class_key="retired.task",
    )
    promoter = _promoter(tmp_path, store)

    await store.write(bad_signature)
    await store.write(retired)
    path = tmp_path / "recipes" / "tampered_recipe@0.1.0.skill.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("tampered_recipe recipe description", "changed"),
        "utf-8",
    )

    with pytest.raises(RecipeSignatureError):
        await promoter.promote(bad_signature.name)
    with pytest.raises(RecipeAlreadyRetiredError):
        await promoter.promote(retired.name)
