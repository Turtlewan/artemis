"""Capability store port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from artemis.types import Skill, SkillDraft, StagedSkill


@runtime_checkable
class CapabilityStore(Protocol):
    async def stage(self, draft: SkillDraft) -> StagedSkill:
        """Write an authored capability to the quarantine staging area."""
        ...

    async def promote(self, staged_id: str) -> Skill:
        """Promote a staged skill that passed the test-before-trust gate into the library."""
        ...

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        tags: Sequence[str] | None = None,
    ) -> list[Skill]:
        """Semantic retrieval by description embedding + optional tag filter."""
        ...

    def get(self, name: str) -> Skill | None: ...
