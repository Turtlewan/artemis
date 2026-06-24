"""Mode profiles for the bounded deep-research engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ResearchMode(StrEnum):
    """Available deep-research orchestration profiles."""

    STANDARD = "standard"
    DEEP = "deep"


@dataclass(frozen=True)
class ResearchProfile:
    """Tunable execution bounds for one research mode."""

    orchestrator_role: str
    max_iterations: int
    sources_per_iter: int
    per_source_max_tokens: int
    search_count: int


def profile_for(mode: ResearchMode) -> ResearchProfile:
    """Return the static execution profile for ``mode``."""

    if mode is ResearchMode.STANDARD:
        return ResearchProfile(
            orchestrator_role="research_orchestrator_standard",
            max_iterations=5,
            sources_per_iter=4,
            per_source_max_tokens=1024,
            search_count=8,
        )
    return ResearchProfile(
        orchestrator_role="research_orchestrator_deep",
        max_iterations=8,
        sources_per_iter=6,
        per_source_max_tokens=1536,
        search_count=10,
    )
