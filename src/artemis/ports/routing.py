"""Router port — request classification before the Brain.

Sync: the router is embedding-cosine only, no network I/O in the
classification step (the embedding call happens in the caller).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from artemis.ports.types import Scope


class RouteDecision:
    """The result of routing a request."""

    def __init__(
        self,
        path: str,
        candidate_tools: list[str],
        confidence: float,
    ) -> None:
        self.path = path  # Literal["deterministic", "local", "escalate"]
        self.candidate_tools = candidate_tools
        self.confidence = confidence


@runtime_checkable
class Router(Protocol):
    """Request router — classifies a query into a tool path.

    Async — the router calls the embedder via ``ToolRegistry.retrieve_tools_scored``
    which is a network I/O call (ADR-015).
    """

    async def route(self, request_text: str, scope: Scope) -> RouteDecision:
        """Route a request to a tool path.

        Returns a RouteDecision with the path, candidate tool fq ids,
        and a confidence score.
        """
        ...
