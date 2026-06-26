"""Structured email extract contract for reaction claim-check payloads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

EMAIL_DETECTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "has_commitment": {"type": "boolean"},
        "has_event": {"type": "boolean"},
        "has_gift_signal": {"type": "boolean"},
        "event_kind": {"type": "string", "enum": ["flight", "meeting"]},
        "title": {"type": "string", "maxLength": 200},
        "start_datetime": {"type": "string", "maxLength": 64},
        "end_datetime": {"type": "string", "maxLength": 64},
        "location": {"type": "string", "maxLength": 300},
        "description": {"type": "string", "maxLength": 1000},
        "attendee_emails": {
            "type": "array",
            "items": {"type": "string", "maxLength": 254},
            "maxItems": 20,
        },
        "origin": {"type": "string", "maxLength": 120},
        "destination": {"type": "string", "maxLength": 120},
        "confirmation_ref": {"type": "string", "maxLength": 120},
        "co_travellers": {
            "type": "array",
            "items": {"type": "string", "maxLength": 200},
            "maxItems": 20,
        },
        "gift_item": {"type": "string", "maxLength": 200},
        "gift_recipient": {"type": "string", "maxLength": 200},
    },
    "additionalProperties": False,
}
"""Bounded model-output schema. Trusted ``source_ref`` and ``summary`` are excluded."""


class StructuredEmailExtract(BaseModel):
    """Laundered, owner-private email facts structured for reaction consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_ref: str
    summary: str = Field(max_length=2000)
    has_commitment: bool = False
    has_event: bool = False
    has_gift_signal: bool = False
    event_kind: str | None = None
    title: str | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None
    location: str | None = None
    description: str | None = None
    attendee_emails: tuple[str, ...] = ()
    origin: str | None = None
    destination: str | None = None
    confirmation_ref: str | None = None
    co_travellers: tuple[str, ...] = ()
    gift_item: str | None = None
    gift_recipient: str | None = None
