"""Privileged-side structuring for laundered Gmail extracts.

The classifier consumes only ``Extract.summary`` and ``Extract.claims`` after
quarantine laundering. It calls the injected local responder role with bounded
structured output, never raw email content, and logs fail-safe ``None`` returns
instead of aborting the ingest path.
"""

from __future__ import annotations

import json
import logging

from artemis.ports.model import ModelPort
from artemis.ports.types import Message
from artemis.untrusted.quarantine import Extract

from .structured import EMAIL_DETECTION_SCHEMA, StructuredEmailExtract

logger = logging.getLogger(__name__)

_DETECT_INSTRUCTION = (
    "Structure this laundered email extract for local-only reactions. "
    "Use only the supplied summary and claims. Return JSON matching the schema. "
    "Do not include source_ref or summary."
)

_STRING_LIMITS: dict[str, int] = {
    "event_kind": 20,
    "title": 200,
    "start_datetime": 64,
    "end_datetime": 64,
    "location": 300,
    "description": 1000,
    "origin": 120,
    "destination": 120,
    "confirmation_ref": 120,
    "gift_item": 200,
    "gift_recipient": 200,
}
_BOOL_FIELDS = frozenset({"has_commitment", "has_event", "has_gift_signal"})
_ARRAY_LIMITS: dict[str, tuple[int, int]] = {
    "attendee_emails": (20, 254),
    "co_travellers": (20, 200),
}


class EmailClassifier:
    """Classify laundered email extracts into owner-private structured fields."""

    def __init__(self, model: ModelPort, role: str = "responder") -> None:
        self._model = model
        self._role = role

    async def classify(self, extract: Extract) -> StructuredEmailExtract | None:
        if not extract.usable:
            logger.warning(
                "email structuring skipped for non-usable extract %s", extract.source_url
            )
            return None

        text = "\n".join([extract.summary, *extract.claims]).strip()
        if not text:
            logger.warning("email structuring skipped for empty extract %s", extract.source_url)
            return None

        try:
            resp = await self._model.complete(
                role=self._role,
                messages=[
                    Message(role="system", content=_DETECT_INSTRUCTION),
                    Message(role="user", content=text),
                ],
                response_schema=EMAIL_DETECTION_SCHEMA,
                max_tokens=512,
            )
            data = json.loads(resp.text)
            return StructuredEmailExtract(
                source_ref=extract.source_url,
                summary=extract.summary[:2000],
                **_coerce(data),
            )
        except Exception:
            logger.warning("email structuring failed for %s", extract.source_url, exc_info=True)
            return None


def _coerce(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("email detection payload must be an object")

    data: dict[str, object] = {}
    for field in _BOOL_FIELDS:
        value = payload.get(field)
        if isinstance(value, bool):
            data[field] = value

    for field, limit in _STRING_LIMITS.items():
        value = payload.get(field)
        if isinstance(value, str):
            if field == "event_kind" and value not in {"flight", "meeting"}:
                continue
            data[field] = value[:limit]

    for field, (max_items, item_limit) in _ARRAY_LIMITS.items():
        value = payload.get(field)
        if isinstance(value, list | tuple):
            data[field] = tuple(
                item[:item_limit] for item in value[:max_items] if isinstance(item, str)
            )

    return data
