"""Transport-neutral intent routing for owner requests."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from artemis.ports.model import ModelPort
from artemis.types import Message

Route = Literal["build", "web_q", "aggregate", "plain_ask"]

_log = logging.getLogger(__name__)

_SYSTEM = (
    "You classify one owner message for Artemis. Return only JSON matching the schema. "
    "Routes: build=the owner asks Artemis to CREATE or make a capability/tool/integration; "
    "web_q=a factual question needing current web information; "
    "aggregate=a broad multi-source research, monitoring, comparison, or summary ask; "
    "plain_ask=everything else, including chat, reasoning, and questions needing no external data."
)


class Intent(BaseModel):
    """A classified route decision for a single inbound owner message."""

    model_config = ConfigDict(frozen=True)

    route: Route
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


_INTENT_SCHEMA: dict[str, Any] = Intent.model_json_schema()


class IntentRouter:
    """Classify user text into the small set of brain-side execution routes."""

    def __init__(self, model: ModelPort) -> None:
        self._model = model

    async def classify(self, text: str) -> Intent:
        """Return the Haiku-classified intent for ``text``."""
        try:
            response = await self._model.complete(
                messages=[
                    Message(role="system", content=_SYSTEM),
                    Message(role="user", content=text),
                ],
                model="haiku",
                response_schema=_INTENT_SCHEMA,
                temperature=0.0,
                max_tokens=200,
            )
            return Intent.model_validate_json(response.text)
        except Exception as exc:
            _log.warning("intent_classify_degraded reason=%s", type(exc).__name__)
            return Intent(route="plain_ask", confidence=0.0, reason="classifier unavailable")
