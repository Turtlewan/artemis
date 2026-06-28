from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.gateway import _register_modules
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.productivity import tools
from artemis.ports.types import Vector


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


def test_live_task_registry_excludes_owner_only_writes(tmp_path: Path) -> None:
    registry = _register_modules(
        FakeEmbedder(),
        settings=Settings(data_root=tmp_path, slot="dev"),
        key_provider=FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True),
    )

    tasks = registry.manifests()["tasks"]
    registered = {f"{tasks.name}.{tool.name}" for tool in tasks.tools}

    assert {
        "tasks.list",
        "tasks.get",
        "tasks.search",
        "tasks.today",
        "tasks.upcoming",
        "tasks.overdue",
        "tasks.suggestion.create",
        "tasks.suggestion.list",
    } <= registered
    assert {
        "tasks.create",
        "tasks.cancel",
        "tasks.complete",
        "tasks.update",
        "tasks.set_recurrence",
        "tasks.assign_to_project",
        "tasks.schedule",
        "tasks.suggestion.accept",
        "tasks.suggestion.reject",
    }.isdisjoint(registered)


async def test_live_task_tools_raise_scope_locked_without_crashing(tmp_path: Path) -> None:
    registry = _register_modules(
        FakeEmbedder(),
        settings=Settings(data_root=tmp_path, slot="dev"),
        key_provider=FakeKeyProvider(owner_unlocked=False),
    )
    list_tool = registry.get_tool("tasks.list")

    with pytest.raises(ScopeLockedError):
        await list_tool.callable_ref(tools.TaskListArgs())


def test_owner_only_routes_do_not_import_calendar_module() -> None:
    source = Path("src/artemis/api_app.py").read_text(encoding="utf-8")

    assert "artemis.modules.calendar" not in source
