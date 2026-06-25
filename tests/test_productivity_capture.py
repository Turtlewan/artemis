from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ingest.connectors import Source
from artemis.ingest.pipeline import IngestPipeline, IngestResult
from artemis.memory import MemoryWriteQueue
from artemis.modules.productivity import tools
from artemis.modules.productivity.capture import (
    COMMITMENT_SCHEMA,
    CaptureService,
    build_capture_pattern_key,
)
from artemis.modules.productivity.manifest import productivity_manifest, projects_manifest
from artemis.modules.productivity.store import ProductivityStore
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Vector
from artemis.recipes import ActionClass, Promoter, Recipe, RecipeStatus, RecipeStore, ReviewSurface
from artemis.untrusted import Extract, QuarantinedReader


class FakeModelPort:
    last_user_content: str | None = None

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, response_schema, temperature, max_tokens
        self.last_user_content = messages[-1].content
        if "not a task" in self.last_user_content.lower():
            payload = {"is_commitment": False, "title": "", "commitment_shape": "other"}
        else:
            payload = {
                "is_commitment": True,
                "title": "Send the report",
                "due": None,
                "commitment_shape": "will_send",
            }
        return ModelResponse(text=json.dumps(payload), origin="local", model_id="fake")

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature
        raise NotImplementedError

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


class FakeQuarantinedReader:
    fixed_summary = "I'll send the report on Friday"

    async def read(
        self,
        *,
        raw_content: str,
        source_url: str,
        source_domain: str,
        query: str,
        max_tokens: int = 1024,
    ) -> Extract:
        del raw_content, source_url, source_domain, query, max_tokens
        return Extract(
            source_url="",
            source_domain="email",
            summary=self.fixed_summary,
            claims=(),
            flagged_injection=False,
            parse_failed=False,
            tokens_used=0,
        )


class FakeFailingQuarantinedReader(FakeQuarantinedReader):
    async def read(
        self,
        *,
        raw_content: str,
        source_url: str,
        source_domain: str,
        query: str,
        max_tokens: int = 1024,
    ) -> Extract:
        del raw_content, source_url, source_domain, query, max_tokens
        return Extract(
            source_url="",
            source_domain="email",
            summary="",
            claims=(),
            flagged_injection=False,
            parse_failed=True,
            tokens_used=0,
        )


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


class FakeRecurrenceStore:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def note(self, key: str) -> int:
        self.counts[key] = self.count(key) + 1
        return self.counts[key]

    def count(self, key: str) -> int:
        return self.counts.get(key, 0)

    def reset(self, key: str) -> None:
        self.counts.pop(key, None)


class FakePromoter:
    def __init__(
        self,
        store: FakeRecipeStore,
        recurrence: FakeRecurrenceStore,
        threshold: int = 2,
    ) -> None:
        self.store = store
        self.recurrence = recurrence
        self.threshold = threshold

    async def note_occurrence(self, task_class_key: str) -> None:
        candidates = [
            recipe
            for recipe in self.store.list(status=RecipeStatus.CANDIDATE)
            if recipe.task_class_key == task_class_key
        ]
        if not candidates:
            return
        count = self.recurrence.note(task_class_key)
        if count >= self.threshold:
            await self.store.set_status(candidates[0].name, RecipeStatus.PENDING)


@dataclass
class FakeIngestPipeline:
    calls: list[Source] = field(default_factory=list)
    fail: bool = False

    async def ingest(self, source: Source) -> IngestResult:
        self.calls.append(source)
        if self.fail:
            raise RuntimeError("ingest failed")
        return cast(IngestResult, object())


@dataclass
class FakeMemoryWriteQueue:
    calls: list[tuple[str, str]] = field(default_factory=list)

    def enqueue(
        self,
        text: str,
        turn_id: str,
        role: str | None = None,
        *,
        source_sensitivity: object | None = None,
    ) -> None:
        del role, source_sensitivity
        self.calls.append((text, turn_id))


@pytest.fixture
def store(tmp_path: Path) -> ProductivityStore:
    return ProductivityStore(
        Settings(data_root=tmp_path, slot="dev"),
        FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True),
    )


@pytest.fixture
def recipe_store() -> FakeRecipeStore:
    return FakeRecipeStore()


@pytest.fixture
def recurrence_store() -> FakeRecurrenceStore:
    return FakeRecurrenceStore()


def _capture_service(
    store: ProductivityStore,
    model: FakeModelPort | None = None,
    quarantine: object | None = None,
    recipe_store: FakeRecipeStore | None = None,
    recurrence_store: FakeRecurrenceStore | None = None,
) -> CaptureService:
    recipes = recipe_store or FakeRecipeStore()
    recurrence = recurrence_store or FakeRecurrenceStore()
    promoter = FakePromoter(recipes, recurrence)
    return CaptureService(
        store=store,
        model=model or FakeModelPort(),
        quarantine=cast(QuarantinedReader | None, quarantine or FakeQuarantinedReader()),
        recipe_store=cast(RecipeStore, recipes),
        promoter=cast(Promoter, promoter),
    )


async def test_commitment_detection_trusted_path(store: ProductivityStore) -> None:
    svc = _capture_service(store)
    suggestion_id = await svc.suggest_from_text("chat", "I'll send the report")

    assert suggestion_id is not None
    suggestions = store.list_suggestions(status="pending")
    assert suggestions[0]["title"] == "Send the report"
    assert suggestions[0]["source"] == "chat"
    assert suggestions[0]["raw_context"] is None


async def test_commitment_detection_non_task_returns_none(store: ProductivityStore) -> None:
    svc = _capture_service(store)

    assert await svc.suggest_from_text("chat", "not a task") is None
    assert store.list_suggestions(status="pending") == []


async def test_email_quarantine_gate_uses_extract_summary(store: ProductivityStore) -> None:
    model = FakeModelPort()
    quarantine = FakeQuarantinedReader()
    svc = _capture_service(store, model=model, quarantine=quarantine)

    suggestion_id = await svc.suggest_from_text("email", "I'll send the report", untrusted=True)

    assert suggestion_id is not None
    assert model.last_user_content == quarantine.fixed_summary
    suggestion = store.list_suggestions(status="pending")[0]
    assert suggestion["raw_context"] is None


async def test_email_quarantine_required(store: ProductivityStore) -> None:
    svc = _capture_service(store, quarantine=None)
    svc.quarantine = None

    with pytest.raises(ValueError, match="quarantine required"):
        await svc.suggest_from_text("email", "I'll send the report", untrusted=True)


async def test_email_parse_failure_degrades(store: ProductivityStore) -> None:
    svc = _capture_service(store, quarantine=FakeFailingQuarantinedReader())

    assert await svc.suggest_from_text("email", "I'll send the report", untrusted=True) is None


def test_commitment_schema_and_pattern_key_normalisation() -> None:
    assert COMMITMENT_SCHEMA["type"] == "object"
    assert COMMITMENT_SCHEMA["required"] == ["is_commitment", "title", "commitment_shape"]
    assert build_capture_pattern_key("email", "will_send") == "email:will_send"
    assert build_capture_pattern_key("EMAIL", "WILL_SEND") == "email:will_send"
    assert build_capture_pattern_key("sms", "will_send") == "other:will_send"
    assert build_capture_pattern_key("email", "unknown_verb") == "email:other"


async def test_graduation_below_threshold(
    store: ProductivityStore,
    recipe_store: FakeRecipeStore,
    recurrence_store: FakeRecurrenceStore,
) -> None:
    svc = _capture_service(store, recipe_store=recipe_store, recurrence_store=recurrence_store)
    suggestion_id = store.create_suggestion(
        "Send the report",
        source="email",
        commitment_shape="will_send",
    )

    task_id = await svc.accept_with_graduation(suggestion_id)

    assert store.get_task(task_id) is not None
    assert recurrence_store.count("email:will_send") == 1
    assert recipe_store.list(status=RecipeStatus.CANDIDATE) == []


async def test_graduation_at_threshold_writes_gated_pending_recipe(
    store: ProductivityStore,
    recipe_store: FakeRecipeStore,
    recurrence_store: FakeRecurrenceStore,
) -> None:
    svc = _capture_service(store, recipe_store=recipe_store, recurrence_store=recurrence_store)
    for _ in range(2):
        suggestion_id = store.create_suggestion(
            "Send the report",
            source="email",
            commitment_shape="will_send",
        )
        await svc.accept_with_graduation(suggestion_id)

    recipes = [
        recipe for recipe in recipe_store.list() if recipe.task_class_key == "email:will_send"
    ]
    assert len(recipes) == 1
    recipe = recipes[0]
    assert recipe.name.startswith("capture_email_will_send")
    assert recipe.action_class == ActionClass.TOUCHES_DATA
    assert recipe.status in {RecipeStatus.PENDING}
    assert all(item.status != RecipeStatus.ENABLED for item in recipes)

    review = ReviewSurface(
        cast(RecipeStore, recipe_store),
        cast(Promoter, FakePromoter(recipe_store, recurrence_store)),
    )
    assert [item.name for item in review.pending_for_review()] == [recipe.name]


async def test_graduation_idempotency(
    store: ProductivityStore,
    recipe_store: FakeRecipeStore,
    recurrence_store: FakeRecurrenceStore,
) -> None:
    svc = _capture_service(store, recipe_store=recipe_store, recurrence_store=recurrence_store)
    for _ in range(3):
        suggestion_id = store.create_suggestion(
            "Send the report",
            source="email",
            commitment_shape="will_send",
        )
        await svc.accept_with_graduation(suggestion_id)

    recipes = [
        recipe for recipe in recipe_store.list() if recipe.task_class_key == "email:will_send"
    ]
    assert len(recipes) == 1
    assert recipes[0].status == RecipeStatus.PENDING


async def test_knowledge_push_on_project_complete(store: ProductivityStore) -> None:
    ingest = FakeIngestPipeline()
    queue = FakeMemoryWriteQueue()
    tools.init_tools(store)
    tools.init_capture(
        _capture_service(store),
        cast(IngestPipeline, ingest),
        cast(MemoryWriteQueue, queue),
        store.settings,
    )
    project_id = store.create_project("Launch", notes="Shipped")

    result = await tools.project_complete(tools.ProjectCompleteArgs(id=project_id))

    assert result.ok is True
    assert len(ingest.calls) == 1
    assert len(queue.calls) == 1
    assert queue.calls[0][1].startswith("project_complete:")


async def test_knowledge_push_failure_degrades(store: ProductivityStore) -> None:
    ingest = FakeIngestPipeline(fail=True)
    queue = FakeMemoryWriteQueue()
    tools.init_tools(store)
    tools.init_capture(
        _capture_service(store),
        cast(IngestPipeline, ingest),
        cast(MemoryWriteQueue, queue),
        store.settings,
    )
    project_id = store.create_project("Launch", notes="Shipped")

    result = await tools.project_complete(tools.ProjectCompleteArgs(id=project_id))

    assert result.ok is True
    assert len(ingest.calls) == 1
    assert queue.calls == []


def test_manifest_smoke_live_split(store: ProductivityStore) -> None:
    tasks = productivity_manifest(
        store,
        None,
        None,
        object(),
        _capture_service(store),
        cast(IngestPipeline, FakeIngestPipeline()),
        cast(MemoryWriteQueue, FakeMemoryWriteQueue()),
    )
    projects = projects_manifest(store)
    task_names = [tool.name for tool in tasks.tools]
    project_names = [tool.name for tool in projects.tools]

    assert len(tasks.tools) == 17
    assert len(projects.tools) == 6
    assert "project.complete" in task_names
    assert "complete" not in project_names
    assert len(task_names) == len(set(task_names))
    assert len(project_names) == len(set(project_names))
