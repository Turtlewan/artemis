from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.gmail.classify import EmailClassifier
from artemis.modules.gmail.extract_store import EmailExtractStore
from artemis.modules.gmail.structured import EMAIL_DETECTION_SCHEMA, StructuredEmailExtract
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Vector
from artemis.untrusted.quarantine import Extract

KEY = b"5" * 32


class FakeModel:
    def __init__(self, payload: dict[str, object] | None = None, *, raises: bool = False) -> None:
        self.payload = payload or {}
        self.raises = raises
        self.calls = 0
        self.messages: list[Message] = []
        self.response_schema: dict[str, object] | None = None

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = role, temperature, max_tokens
        self.calls += 1
        self.messages = list(messages)
        self.response_schema = response_schema
        if self.raises:
            raise RuntimeError("model unavailable")
        return ModelResponse(text=json.dumps(self.payload))

    async def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        _ = role, messages, temperature
        if False:
            yield ""

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        _ = role
        return [[float(len(text))] for text in texts]


def _extract(
    *,
    summary: str = "Flight to Zurich.",
    claims: tuple[str, ...] = ("Confirmation ABC123.",),
    flagged_injection: bool = False,
    parse_failed: bool = False,
) -> Extract:
    return Extract(
        source_url="gmail:msg-1",
        source_domain="gmail",
        summary=summary,
        claims=claims,
        flagged_injection=flagged_injection,
        parse_failed=parse_failed,
        tokens_used=10,
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)


def _store(tmp_path: Path) -> EmailExtractStore:
    key_provider = FakeKeyProvider({OWNER_PRIVATE: KEY}, owner_unlocked=True)
    return EmailExtractStore(_settings(tmp_path), key_provider)


def _assert_schema_accepts(payload: dict[str, object]) -> None:
    schema_properties = EMAIL_DETECTION_SCHEMA["properties"]
    assert isinstance(schema_properties, dict)
    assert not (set(payload) - set(schema_properties))

    for key, value in payload.items():
        field_schema = schema_properties[key]
        assert isinstance(field_schema, dict)
        field_type = field_schema["type"]
        if field_type == "boolean":
            assert isinstance(value, bool)
        elif field_type == "string":
            assert isinstance(value, str)
            assert len(value) <= int(field_schema.get("maxLength", len(value)))
            enum = field_schema.get("enum")
            if enum is not None:
                assert value in enum
        elif field_type == "array":
            assert isinstance(value, list)
            assert len(value) <= int(field_schema["maxItems"])
            item_schema = field_schema["items"]
            assert isinstance(item_schema, dict)
            assert all(isinstance(item, str) for item in value)
            assert all(len(item) <= int(item_schema["maxLength"]) for item in value)
        else:
            raise AssertionError(f"unexpected schema type {field_type}")


def test_structured_contract_defaults_extra_forbid_and_schema_samples() -> None:
    extract = StructuredEmailExtract(source_ref="gmail:1", summary="summary")

    assert extract.has_commitment is False
    assert extract.has_event is False
    assert extract.has_gift_signal is False
    assert extract.attendee_emails == ()
    assert extract.co_travellers == ()
    with pytest.raises(ValidationError):
        StructuredEmailExtract.model_validate(
            {"source_ref": "gmail:1", "summary": "summary", "unknown": True}
        )

    _assert_schema_accepts(
        {
            "has_event": True,
            "event_kind": "flight",
            "title": "Flight to Zurich",
            "start_datetime": "2026-07-01T08:00:00Z",
            "origin": "SIN",
            "destination": "ZRH",
            "confirmation_ref": "ABC123",
            "co_travellers": ["Ashley"],
        }
    )
    _assert_schema_accepts(
        {
            "has_commitment": True,
            "has_event": True,
            "event_kind": "meeting",
            "title": "Planning sync",
            "start_datetime": "2026-07-02T09:00:00Z",
            "end_datetime": "2026-07-02T09:30:00Z",
            "location": "Office",
            "attendee_emails": ["alice@example.com"],
        }
    )
    _assert_schema_accepts(
        {
            "has_gift_signal": True,
            "gift_item": "coffee grinder",
            "gift_recipient": "Ashley",
        }
    )


@pytest.mark.asyncio
async def test_classifier_maps_flight_fields_and_uses_laundered_text() -> None:
    model = FakeModel(
        {
            "has_event": True,
            "event_kind": "flight",
            "title": "Flight to Zurich",
            "start_datetime": "2026-07-01T08:00:00Z",
            "origin": "SIN",
            "destination": "ZRH",
            "confirmation_ref": "ABC123",
            "co_travellers": ["Ashley"],
        }
    )

    structured = await EmailClassifier(model).classify(_extract())

    assert structured is not None
    assert structured.source_ref == "gmail:msg-1"
    assert structured.summary == "Flight to Zurich."
    assert structured.has_event is True
    assert structured.event_kind == "flight"
    assert structured.start_datetime == "2026-07-01T08:00:00Z"
    assert structured.co_travellers == ("Ashley",)
    assert model.response_schema == EMAIL_DETECTION_SCHEMA
    assert [message.role for message in model.messages] == ["system", "user"]
    assert model.messages[1].content == "Flight to Zurich.\nConfirmation ABC123."


@pytest.mark.asyncio
async def test_classifier_maps_gift_signal() -> None:
    model = FakeModel(
        {
            "has_gift_signal": True,
            "gift_item": "coffee grinder",
            "gift_recipient": "Ashley",
        }
    )

    structured = await EmailClassifier(model).classify(_extract(summary="Gift idea."))

    assert structured is not None
    assert structured.has_gift_signal is True
    assert structured.gift_item == "coffee grinder"
    assert structured.gift_recipient == "Ashley"


@pytest.mark.asyncio
async def test_classifier_trusted_fields_not_shadowable_and_summary_capped() -> None:
    model = FakeModel(
        {
            "source_ref": "gmail:attacker",
            "summary": "attacker summary",
            "has_commitment": True,
        }
    )
    long_summary = "x" * 3000

    structured = await EmailClassifier(model).classify(_extract(summary=long_summary, claims=()))

    assert structured is not None
    assert structured.source_ref == "gmail:msg-1"
    assert structured.summary == "x" * 2000
    assert structured.has_commitment is True


@pytest.mark.asyncio
async def test_classifier_non_usable_empty_and_failure_return_none_with_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    non_usable_model = FakeModel({"has_event": True})
    non_usable = await EmailClassifier(non_usable_model).classify(_extract(flagged_injection=True))
    assert non_usable is None
    assert non_usable_model.calls == 0
    assert "email structuring skipped for non-usable extract gmail:msg-1" in caplog.text

    empty_model = FakeModel({"has_event": True})
    empty = await EmailClassifier(empty_model).classify(_extract(summary="", claims=()))
    assert empty is None
    assert empty_model.calls == 0
    assert "email structuring skipped for empty extract gmail:msg-1" in caplog.text

    failing_model = FakeModel(raises=True)
    failed = await EmailClassifier(failing_model).classify(_extract())
    assert failed is None
    records = [
        record
        for record in caplog.records
        if record.message == "email structuring failed for gmail:msg-1"
    ]
    assert len(records) == 1
    assert records[0].exc_info is not None


def test_store_round_trips_fetches_missing_and_prunes_stale(tmp_path: Path) -> None:
    store = _store(tmp_path)
    fresh = StructuredEmailExtract(
        source_ref="gmail:fresh",
        summary="fresh",
        has_event=True,
        event_kind="meeting",
        start_datetime="2026-07-01T08:00:00Z",
    )
    stale = StructuredEmailExtract(
        source_ref="gmail:stale",
        summary="stale",
        has_gift_signal=True,
        gift_item="coffee grinder",
        gift_recipient="Ashley",
    )

    store.put(fresh)
    store.put(stale)
    assert store.fetch("gmail:fresh") == fresh
    assert store.fetch("missing") is None

    with store._connect() as conn:
        conn.execute(
            "UPDATE email_extract SET stored_at = ? WHERE source_ref = ?",
            ("2026-01-01T00:00:00Z", "gmail:stale"),
        )
        conn.execute(
            "UPDATE email_extract SET stored_at = ? WHERE source_ref = ?",
            ("2026-06-01T00:00:00Z", "gmail:fresh"),
        )

    store.prune_older_than("2026-03-01T00:00:00Z")

    assert store.fetch("gmail:stale") is None
    assert store.fetch("gmail:fresh") == fresh
