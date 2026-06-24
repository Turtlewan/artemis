from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Literal, cast

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import DataScope, ModuleManifest
from artemis.modules.gmail import FakeGmailApi, GmailReadCache, MailCategory, build_gmail_manifest
from artemis.modules.gmail.cache import CachedMessage
from artemis.modules.gmail.hook import build_gmail_urgency_hook, build_known_senders
from artemis.modules.gmail.urgency import GmailUrgencyPreFilter, UrgencyTemplateRenderer
from artemis.ports.model import ModelResponse
from artemis.ports.types import AsOf, Fact, Message, PersonId, Vector
from artemis.proactive.hit_handler import TemplateRegistry
from artemis.proactive.hook_types import HookResult
from artemis.untrusted.quarantine import QuarantinedReader

KEY = b"2" * 32


class FakeModel:
    def __init__(self, *, parse_failed: bool = False) -> None:
        self.parse_failed = parse_failed
        self.calls = 0

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = role, messages, response_schema, temperature, max_tokens
        self.calls += 1
        if self.parse_failed:
            return ModelResponse(text="not-json")
        return ModelResponse(
            text=json.dumps(
                {"summary": "Reply is time sensitive.", "claims": [], "flagged_injection": False}
            )
        )

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


class FakeMemoryStore:
    def __init__(self, *, facts: list[Fact] | None = None, raises: bool = False) -> None:
        self.facts = facts or []
        self.raises = raises

    async def add_fact(self, person_id: PersonId, fact: Fact) -> None:
        _ = person_id, fact

    async def recall(
        self,
        person_id: PersonId,
        query: str,
        k: int = 10,
        as_of: AsOf | None = None,
    ) -> list[Fact]:
        _ = person_id, query, k, as_of
        if self.raises:
            raise RuntimeError("boom")
        return self.facts

    async def update_fact(self, person_id: PersonId, fact_id: str, fact: Fact) -> None:
        _ = person_id, fact_id, fact

    def delete_fact(self, person_id: PersonId, fact_id: str) -> None:
        _ = person_id, fact_id

    async def inject_context(
        self,
        person_id: PersonId,
        token_budget: int,
        as_of: AsOf | None = None,
    ) -> list[Fact]:
        _ = person_id, token_budget, as_of
        return []


class CountingGmailApi(FakeGmailApi):
    def __init__(self, *, messages: dict[str, dict[str, object]]) -> None:
        super().__init__(messages=messages)
        self.get_calls = 0

    def get_message(
        self, message_id: str, *, fmt: Literal["full", "metadata"]
    ) -> dict[str, object]:
        self.get_calls += 1
        return dict(super().get_message(message_id, fmt=fmt))


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, gmail_attachment_max_mb=1)


def _cache(tmp_path: Path) -> GmailReadCache:
    key_provider = FakeKeyProvider({OWNER_PRIVATE: KEY}, owner_unlocked=True)
    return GmailReadCache(_settings(tmp_path), key_provider)


def _cached(
    message_id: str,
    *,
    sender: str = "Alice Smith <alice@example.com>",
    subject: str = "Subject",
    snippet: str = "snippet",
    internal_date_ms: int = 1,
    category: MailCategory = MailCategory.PRIMARY,
    unread: bool = True,
    important: bool = True,
) -> CachedMessage:
    return CachedMessage(
        message_id=message_id,
        thread_id=f"thread-{message_id}",
        history_id="h1",
        sender=sender,
        subject=subject,
        internal_date_ms=internal_date_ms,
        category=category,
        snippet=snippet,
        label_ids=("INBOX", "UNREAD"),
        has_attachments=False,
        unread=unread,
        important=important,
        body_ingested=False,
    )


def _body_data(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _api_message(message_id: str, body: str = "Please reply today.") -> dict[str, object]:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "historyId": "h1",
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": _body_data(body), "size": len(body)},
            "headers": [],
        },
    }


def _reader(model: FakeModel | None = None) -> QuarantinedReader:
    return QuarantinedReader(model or FakeModel(), "reader")


def test_stage1_prefilter_defaults_to_important_primary_and_updates(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    rows = [
        _cached("a", internal_date_ms=10, category=MailCategory.PRIMARY),
        _cached("b", internal_date_ms=20, unread=False, category=MailCategory.PRIMARY),
        _cached("c", internal_date_ms=30, important=False, category=MailCategory.PRIMARY),
        _cached("d", internal_date_ms=40, category=MailCategory.PROMOTIONS),
        _cached("e", internal_date_ms=50, category=MailCategory.UPDATES),
        _cached("f", internal_date_ms=60, category=MailCategory.FORUMS),
    ]
    for row in rows:
        cache.upsert(row)

    candidates = GmailUrgencyPreFilter(cache).stage1_candidates()

    assert [(msg.message_id, reason) for msg, reason in candidates] == [
        ("e", "important"),
        ("a", "important"),
    ]


def test_stage2_known_sender_match_and_empty_degrade(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    alice = _cached("a", sender="Alice Smith <alice@example.com>", internal_date_ms=2)
    bob = _cached("b", sender="Bob Jones <bob@example.com>", internal_date_ms=1)
    cache.upsert(alice)
    cache.upsert(bob)
    candidates = GmailUrgencyPreFilter(cache).stage1_candidates()

    boosted = GmailUrgencyPreFilter(cache, known_senders=frozenset({"alice"})).stage2_boost(
        candidates
    )
    assert [(msg.sender, known) for msg, known, _reason in boosted] == [
        ("Alice Smith <alice@example.com>", True),
        ("Bob Jones <bob@example.com>", False),
    ]

    empty = GmailUrgencyPreFilter(cache, known_senders=frozenset()).stage2_boost(candidates)
    assert [known for _msg, known, _reason in empty] == [False, False]


@pytest.mark.asyncio
async def test_build_known_senders_happy_failure_and_none(caplog: pytest.LogCaptureFixture) -> None:
    person_id = PersonId("owner")
    fact = Fact(
        fact_id="f1",
        person_id=person_id,
        subject="Alice",
        relation="is_contact",
        object="Boss",
        confidence=1.0,
        valid_at=datetime(2024, 1, 1),
    )

    assert await build_known_senders(FakeMemoryStore(facts=[fact]), person_id) == frozenset(
        {"alice", "boss"}
    )
    assert await build_known_senders(None, person_id) == frozenset()
    assert await build_known_senders(FakeMemoryStore(raises=True), person_id) == frozenset()
    assert "known-sender recall failed" in caplog.text


def test_check_ref_misses_empty_and_no_important(tmp_path: Path) -> None:
    empty_cache = _cache(tmp_path / "empty")
    api = CountingGmailApi(messages={})
    hook, _preflight, _register = build_gmail_urgency_hook(empty_cache, api, _reader(), frozenset())
    assert hook.check_ref is not None
    assert hook.check_ref().hit is False
    assert api.get_calls == 0

    cache = _cache(tmp_path / "miss")
    cache.upsert(_cached("m1", important=False, sender="Nobody <nobody@example.com>"))
    hook, _preflight, _register = build_gmail_urgency_hook(
        cache, api, _reader(), frozenset(), max_candidates=10
    )
    assert hook.check_ref is not None
    assert hook.check_ref().hit is False


@pytest.mark.asyncio
async def test_payload_shape_extracts_and_template(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert(_cached("m1", internal_date_ms=2, subject="raw subject", snippet="raw snippet"))
    cache.upsert(_cached("m2", internal_date_ms=1))
    api = CountingGmailApi(messages={"m1": _api_message("m1"), "m2": _api_message("m2")})
    hook, preflight, register = build_gmail_urgency_hook(cache, api, _reader(), frozenset())
    registry = TemplateRegistry()
    register(registry)

    await preflight()
    assert hook.check_ref is not None
    result = hook.check_ref()

    assert result.hit is True
    assert result.dedup_value == date.today().isoformat()
    assert result.payload["unread_count"] == 2
    candidates = result.payload["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 2
    for entry in candidates:
        assert isinstance(entry, dict)
        assert set(entry) == {
            "message_id",
            "sender",
            "known_to_memory",
            "extract_summary",
            "extract_failed",
            "admit_reason",
        }
        assert "subject" not in entry
        assert "snippet" not in entry
        assert entry["sender"] == "Alice Smith"
        assert entry["extract_summary"] == "Reply is time sensitive."
        assert entry["extract_failed"] is False

    assert "Alice Smith" in registry.render("gmail.gmail_urgency_check", result)
    assert UrgencyTemplateRenderer().render(
        HookResult.of(
            {
                "candidates": [
                    {
                        "sender": "Alice",
                        "known_to_memory": False,
                        "extract_summary": "",
                        "extract_failed": True,
                        "message_id": "x",
                        "admit_reason": "important",
                    }
                ],
                "unread_count": 1,
            }
        )
    )
    assert (
        UrgencyTemplateRenderer().render(HookResult.of({"candidates": [], "unread_count": 0}))
        == "No urgent unread messages."
    )


@pytest.mark.asyncio
async def test_extract_failure_degrades_to_hit(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert(_cached("m1"))
    api = CountingGmailApi(messages={"m1": _api_message("m1")})
    hook, preflight, _register = build_gmail_urgency_hook(
        cache, api, _reader(FakeModel(parse_failed=True)), frozenset()
    )

    await preflight()
    assert hook.check_ref is not None
    result = hook.check_ref()

    candidates = result.payload["candidates"]
    assert result.hit is True
    assert isinstance(candidates, list)
    assert candidates[0]["extract_summary"] == ""
    assert candidates[0]["extract_failed"] is True


def test_manifest_wiring_and_hookspec_validation(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    api = CountingGmailApi(messages={})
    no_hook = build_gmail_manifest(api, cache)
    assert no_hook.proactive_hooks == []

    hook, _preflight, _register = build_gmail_urgency_hook(cache, api, _reader(), frozenset())
    manifest = build_gmail_manifest(api, cache, hook=hook)
    assert len(manifest.proactive_hooks) == 1
    assert manifest.proactive_hooks[0].needs_llm is True
    assert hook.tier == 1
    assert hook.needs_llm is True
    assert hook.urgency == "high"
    assert hook.interval_seconds == 300
    assert hook.dedup_key == "gmail_urgency"
    ModuleManifest(
        name="gmail_test",
        version="0.1.0",
        description="test",
        data_scope=DataScope.OWNER_PRIVATE,
        proactive_hooks=[hook],
    )


def test_keyword_or_in_and_no_subject_leak(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert(
        _cached(
            "m1",
            important=False,
            subject="URGENT: legal notice",
            snippet="attacker snippet",
        )
    )

    assert GmailUrgencyPreFilter(cache).stage1_candidates() == []
    widened = GmailUrgencyPreFilter(cache, urgency_keywords=frozenset({"legal"}))
    candidates = widened.stage1_candidates()
    assert [(msg.message_id, reason) for msg, reason in candidates] == [("m1", "keyword")]

    payload = widened.build_payload(widened.stage2_boost(candidates), {})
    payload_candidates = payload["candidates"]
    assert isinstance(payload_candidates, list)
    first = cast(dict[str, object], payload_candidates[0])
    assert first["admit_reason"] == "keyword"
    assert "subject" not in first
    assert "snippet" not in first
    assert "legal notice" not in json.dumps(first)


def test_vip_force_admit_non_important(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert(
        _cached(
            "m1",
            important=False,
            sender="Ashley Tan <ashley@x.com>",
        )
    )

    assert GmailUrgencyPreFilter(cache).stage1_candidates() == []
    candidates = GmailUrgencyPreFilter(cache, vip_senders=frozenset({"ashley"})).stage1_candidates()
    assert [(msg.message_id, reason) for msg, reason in candidates] == [("m1", "vip")]


def test_bank_sender_exclude_wins_and_subdomains(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert(
        _cached(
            "uob",
            sender="UOB <alerts@uob.com.sg>",
            subject="payment warning",
            important=True,
        )
    )
    cache.upsert(
        _cached(
            "dbs",
            sender="DBS <alerts@notify.dbs.com.sg>",
            important=True,
            internal_date_ms=2,
        )
    )

    no_exclude = GmailUrgencyPreFilter(
        cache, urgency_keywords=frozenset({"payment warning"})
    ).stage1_candidates()
    assert {msg.message_id for msg, _reason in no_exclude} == {"uob", "dbs"}

    excluded = GmailUrgencyPreFilter(
        cache,
        urgency_keywords=frozenset({"payment warning"}),
        sender_exclude=frozenset({"uob.com.sg", "dbs.com.sg"}),
    ).stage1_candidates()
    assert excluded == []


def test_hook_static_and_memory_vips_force_admit(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert(_cached("carol", sender="Carol <carol@x.com>", important=False))
    cache.upsert(
        _cached("debby", sender="Debby <debby@x.com>", important=False, internal_date_ms=2)
    )
    api = CountingGmailApi(
        messages={"carol": _api_message("carol"), "debby": _api_message("debby")}
    )
    hook, _preflight, _register = build_gmail_urgency_hook(
        cache, api, _reader(), frozenset({"carol"})
    )

    assert hook.check_ref is not None
    result = hook.check_ref()
    candidates = result.payload["candidates"]
    assert isinstance(candidates, list)
    typed_candidates = cast(list[dict[str, object]], candidates)
    assert [(item["message_id"], item["admit_reason"]) for item in typed_candidates] == [
        ("debby", "vip"),
        ("carol", "vip"),
    ]
