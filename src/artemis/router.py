"""Embedding-based semantic Router — router-first (the frugality core).

Classifies a request into ``deterministic``, ``local``, or ``escalate``
path based on cosine similarity to registered tool prototypes.
"""

from __future__ import annotations

import logging

from artemis.ports.retrieval import EmbeddingModel
from artemis.ports.routing import RouteDecision
from artemis.registry.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SemanticRouter:
    """Embedding-based router — cosine over tool prototypes.

    Implements the ``Router`` port with an async ``route`` method
    (it ``await``s the embedder via ``ToolRegistry.retrieve_tools_scored``).

    Thresholds are configurable via constructor args with documented M1 defaults
    (gated for empirical confirmation at the live-model probe).
    """

    def __init__(
        self,
        registry: ToolRegistry,
        embedder: EmbeddingModel,
        deterministic_threshold: float = 0.6,
        local_threshold: float = 0.35,
        escalate_floor: float = 0.15,
    ) -> None:
        self._registry = registry
        self._embedder = embedder
        self._deterministic_threshold = deterministic_threshold
        self._local_threshold = local_threshold
        self._escalate_floor = escalate_floor

    async def route(self, request_text: str, scope: str) -> RouteDecision:
        """Route a request to a tool path.

        1. Retrieve top-3 tool scores from the registry.
        2. Compare the top score against thresholds.
        3. Return the matching path + candidate tools.
        """
        try:
            scored = await self._registry.retrieve_tools_scored(request_text, k=3)
        except Exception:
            logger.warning(
                "Router: retrieve_tools_scored failed, degrading to escalate", exc_info=True
            )
            return RouteDecision(path="escalate", candidate_tools=[], confidence=0.0)

        if not scored:
            return RouteDecision(path="escalate", candidate_tools=[], confidence=0.0)

        top_fq_id, top_score = scored[0]
        candidate_tools = [fq for fq, _ in scored]

        if top_score >= self._deterministic_threshold:
            path = "deterministic"
        elif top_score >= self._local_threshold:
            path = "local"
        elif top_score < self._escalate_floor:
            path = "escalate"
        else:
            path = "local"

        return RouteDecision(
            path=path,
            candidate_tools=candidate_tools,
            confidence=top_score,
        )
