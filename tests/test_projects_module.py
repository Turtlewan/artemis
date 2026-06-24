from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import DataScope
from artemis.memory.entities import EntityRef, EntityType
from artemis.modules.productivity import ProductivityStore, projects_manifest, tasks_manifest, tools
from artemis.ports.types import Vector
from artemis.registry import ToolRegistry


class FakeEmbedder:
    DIMENSION = 16

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vec(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._hash_vec(query)

    def _hash_vec(self, text: str) -> Vector:
        vec = [0.0] * self.DIMENSION
        for word in text.lower().split():
            bucket = hashlib.sha256(word.encode()).digest()[0] % self.DIMENSION
            vec[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        if norm > 0:
            vec = [value / norm for value in vec]
        return vec


class FakeEntityRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve_or_create_entity(
        self, *, name: str, entity_type: EntityType, entity_id: str
    ) -> EntityRef:
        self.calls.append({"name": name, "entity_type": entity_type, "entity_id": entity_id})
        return EntityRef(module="productivity", entity_id=entity_id)


def test_projects_and_tasks_manifests_split_tool_surfaces(tmp_path: Path) -> None:
    store = _store(tmp_path)
    projects = projects_manifest(store)
    tasks = tasks_manifest(store)

    project_fq_ids = _fq_ids(projects.name, [tool.name for tool in projects.tools])
    task_fq_ids = _fq_ids(tasks.name, [tool.name for tool in tasks.tools])

    assert projects.name == "projects"
    assert projects.data_scope == DataScope.OWNER_PRIVATE
    assert projects.ui.kind == "card"
    assert project_fq_ids == {
        "projects.create",
        "projects.get",
        "projects.list",
        "projects.update",
        "projects.archive",
        "projects.tasks",
    }

    assert tasks.name == "tasks"
    assert tasks.data_scope == DataScope.OWNER_PRIVATE
    assert tasks.ui.kind == "card"
    assert task_fq_ids == {
        "tasks.create",
        "tasks.get",
        "tasks.list",
        "tasks.search",
        "tasks.today",
        "tasks.upcoming",
        "tasks.overdue",
        "tasks.update",
        "tasks.complete",
        "tasks.cancel",
        "tasks.set_recurrence",
        "tasks.assign_to_project",
        "tasks.suggestion.create",
        "tasks.suggestion.list",
        "tasks.suggestion.accept",
        "tasks.suggestion.reject",
    }
    assert len(projects.tools) == 6
    assert len(tasks.tools) == 16
    assert project_fq_ids.isdisjoint(task_fq_ids)


def test_projects_and_tasks_register_together_without_collisions(tmp_path: Path) -> None:
    registry = ToolRegistry(FakeEmbedder())

    registry.register(projects_manifest(_store(tmp_path)))
    registry.register(tasks_manifest(_store(tmp_path)))

    assert set(registry.manifests()) == {"projects", "tasks"}
    assert registry.get_tool("projects.create").name == "create"
    assert registry.get_tool("tasks.create").name == "create"
    assert registry.get_tool("tasks.suggestion.create").name == "suggestion.create"


async def test_project_tasks_reads_tasks_from_the_shared_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    projects = projects_manifest(store)
    tasks_manifest(store)
    project_id = store.create_project("Launch plan")
    task_id = store.create_task("Draft milestones", project_id=project_id)

    project_tasks = next(tool for tool in projects.tools if tool.name == "tasks")
    result = cast(
        tools.TaskListResult,
        await project_tasks.callable_ref(tools.ProjectTasksArgs(id=project_id)),
    )

    assert [task["id"] for task in result.tasks] == [task_id]
    assert result.tasks[0]["project_id"] == project_id


def test_project_create_still_eagerly_links_goal_entity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    fake_entities = FakeEntityRepository()

    project_id = store.create_project("Build import pipeline", entity_repo=fake_entities)
    project = store.get_project(project_id)

    assert project is not None
    assert project["project_goal_entity_id"] == f"goal:{project_id}"
    assert fake_entities.calls == [
        {
            "name": "Build import pipeline",
            "entity_type": EntityType.GOAL,
            "entity_id": f"goal:{project_id}",
        }
    ]


def _fq_ids(module: str, tool_names: list[str]) -> set[str]:
    return {f"{module}.{tool_name}" for tool_name in tool_names}


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")


def _store(tmp_path: Path) -> ProductivityStore:
    return ProductivityStore(
        _settings(tmp_path),
        FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True),
    )
