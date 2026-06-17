"""Text Gateway — attaches scope before the Brain, plus composition helper.

M1 is a single-owner stub: every request gets ``OWNER_SCOPE = "owner-private"``
and a fixed ``OWNER_PERSON_ID``. Voice-ID, login, and guest paths arrive in M2.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from artemis.brain import Brain, BrainResponse
from artemis.config import Settings, get_settings
from artemis.ports.types import PersonId, Scope

if TYPE_CHECKING:
    from artemis.registry import ToolRegistry

logger = logging.getLogger(__name__)

OWNER_PERSON_ID: PersonId = PersonId("owner")
"""Fixed owner identity (M1 single-owner stub — M2 replaces with real resolution)."""

OWNER_SCOPE: Scope = "owner-private"
"""Scope attached to every M1 request."""


class Gateway:
    """Text ingress Gateway — attaches scope before the Brain sees the request.

    The Gateway is the single point that resolves a person → scope and attaches
    it BEFORE the Brain (brain.md's hard ordering). In M1 it's a constant.
    """

    def __init__(self, brain: Brain) -> None:
        self._brain = brain

    async def handle_text(self, request_text: str) -> BrainResponse:
        """Process a text request through the Brain with single-owner scope."""
        logger.debug("Gateway: scope resolution stubbed — attaching OWNER_SCOPE")
        return await self._brain.respond(request_text, OWNER_SCOPE)

    async def handle_text_stream(self, request_text: str) -> AsyncIterator[str]:
        """Stream a text response — single chunk for M1 (token streaming slots in later)."""
        result = await self.handle_text(request_text)
        yield result.text

    async def pre_route(self, request_text: str) -> str | None:
        """Classify a request — returns the top candidate tool id, if any.

        Used by the voice surface (M5-c) to classify Tier pre-serve through
        the same single-owner scope seam.
        """
        logger.debug("Gateway: pre_route scope resolution stubbed — attaching OWNER_SCOPE")
        return await self._brain.pre_route(request_text, OWNER_SCOPE)


def compose_brain(settings: Settings | None = None) -> Brain:
    """Build a wired Brain from settings.

    Constructs the real adapters (``OpenAIEmbeddingModel``, ``OpenAIModelPort``),
    a ``ToolRegistry``, registers available module manifests (silently skips
    modules not yet built), builds a ``SemanticRouter``, and returns the ``Brain``.

    Uses lazy ``ToolRegistry.register()`` — no network at construction time.
    """
    if settings is None:
        settings = get_settings()

    from artemis.adapters.model_adapters import OpenAIEmbeddingModel, OpenAIModelPort

    embedder = OpenAIEmbeddingModel(settings)
    model = OpenAIModelPort(settings)
    registry = _register_modules(embedder)
    from artemis.router import SemanticRouter

    router = SemanticRouter(registry, embedder)
    return Brain(router, registry, model)


def _register_modules(embedder: object) -> ToolRegistry:
    """Register all available module manifests.

    Silently skips modules not yet built (try/except ImportError), so
    ``compose_brain`` works with a partial build.

    Uses lazy ``ToolRegistry.register()`` — no network at construction time.
    """
    from artemis.registry import ToolRegistry

    registry = ToolRegistry(embedder)  # type: ignore[arg-type]

    # ── Time tool (M1-d) ──────────────────────────────────────────────
    try:
        from artemis.tools.time_tool import manifest as time_manifest

        registry.register(time_manifest())
        logger.debug("Gateway: registered time module manifest")
    except ImportError:
        logger.debug("Gateway: time module not available — skipping")

    return registry
