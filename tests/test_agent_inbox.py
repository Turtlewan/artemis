from __future__ import annotations

import asyncio
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from artemis.agentic.inbox import INBOX_NOTICE_BODY_PREFIX, AgentInbox, AskOwnerTool
from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.proactive.hit_handler import OutboundMessage


class RecordingDelivery:
    def __init__(self) -> None:
        self.messages: list[OutboundMessage] = []

    def __call__(self, messages: list[OutboundMessage]) -> int:
        self.messages.extend(messages)
        return len(messages)


class RaisingDelivery:
    def __call__(self, messages: list[OutboundMessage]) -> int:
        raise RuntimeError("ntfy unavailable")


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)


def _key_provider() -> FakeKeyProvider:
    return FakeKeyProvider({OWNER_PRIVATE: b"1" * 32}, owner_unlocked=True)


def _inbox(tmp_path: Path) -> AgentInbox:
    return AgentInbox(_settings(tmp_path), _key_provider())


@pytest.mark.asyncio
async def test_ask_delivers_content_free_notice_and_resolve_releases_waiter(
    tmp_path: Path,
) -> None:
    inbox = _inbox(tmp_path)
    delivery = RecordingDelivery()
    tool = AskOwnerTool(inbox, delivery)
    sensitive_question = "Should I email Alice about the secret acquisition?"

    ask_task = asyncio.create_task(tool.ask(sensitive_question, options=("yes", "no"), timeout_s=5))
    await _wait_for_pending(inbox)
    pending = inbox.pending()

    assert len(pending) == 1
    assert pending[0].prompt == sensitive_question
    assert pending[0].options == ("yes", "no")
    assert len(delivery.messages) == 1

    notice = delivery.messages[0]
    assert notice.title == "Artemis needs a decision"
    assert notice.body == f"{INBOX_NOTICE_BODY_PREFIX}{pending[0].id}"
    assert notice.delivery is not None
    assert notice.delivery.priority == "default"
    assert notice.delivery.tags == ["question"]
    assert sensitive_question not in _flatten_notice_values(notice)

    inbox.resolve(pending[0].id, "yes")
    assert await ask_task == "yes"


@pytest.mark.asyncio
async def test_timeout_returns_none_and_leaves_question_pending(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path)
    tool = AskOwnerTool(inbox, RecordingDelivery())

    answer = await tool.ask("Should this time out?", timeout_s=1)

    assert answer is None
    assert len(inbox.pending()) == 1


def test_persistence_survives_reconstruct_under_owner_private(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    key_provider = _key_provider()
    inbox = AgentInbox(settings, key_provider)

    question_id = inbox.put("Persist this?", ("ok",))

    expected_path = tmp_path / "dev" / OWNER_PRIVATE / "agentic" / "agent_inbox.db"
    assert expected_path.exists()
    assert expected_path.is_relative_to(tmp_path / "dev" / OWNER_PRIVATE)

    reconstructed = AgentInbox(settings, key_provider)
    pending = reconstructed.pending()
    assert [question.id for question in pending] == [question_id]
    assert pending[0].prompt == "Persist this?"
    assert pending[0].options == ("ok",)


def test_ids_are_unguessable_and_not_ordered(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path)

    first = inbox.put("one")
    second = inbox.put("two")

    assert first != second
    assert len(first) >= 32
    assert len(second) >= 32
    assert not first.startswith(second[:8])
    assert not second.startswith(first[:8])


def test_double_resolve_is_no_op(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path)
    question_id = inbox.put("Answer once")

    inbox.resolve(question_id, "a")
    inbox.resolve(question_id, "b")

    row = inbox.get(question_id)
    assert row is not None
    assert row.answer == "a"
    assert inbox.pending() == []


@pytest.mark.asyncio
async def test_delivery_failure_propagates_and_row_stays_pending(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path)
    tool = AskOwnerTool(inbox, RaisingDelivery())

    with pytest.raises(RuntimeError, match="ntfy unavailable"):
        await tool.ask("Still answerable out of band", timeout_s=1)

    pending = inbox.pending()
    assert len(pending) == 1
    assert pending[0].prompt == "Still answerable out of band"
    assert pending[0].answer is None


def test_caller_strings_are_bound_parameters_not_sql(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path)
    prompt = "x'); DROP TABLE agent_question; --"
    answer = "y'); UPDATE agent_question SET answer='owned'; --"

    question_id = inbox.put(prompt, ("a'); DROP TABLE agent_question; --",))
    inbox.resolve(question_id, answer)
    second_id = inbox.put("table still exists")

    first = inbox.get(question_id)
    assert first is not None
    assert first.prompt == prompt
    assert first.answer == answer
    assert [question.id for question in inbox.pending()] == [second_id]


async def _wait_for_pending(inbox: AgentInbox) -> None:
    for _ in range(100):
        if inbox.pending():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out waiting for pending question")


def _flatten_notice_values(value: object) -> str:
    values: list[str] = []
    _collect_values(value, values)
    return "\n".join(values)


def _collect_values(value: object, values: list[str]) -> None:
    if isinstance(value, str):
        values.append(value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_values(key, values)
            _collect_values(item, values)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_values(item, values)
        return
    if is_dataclass(value):
        for field in fields(value):
            _collect_values(getattr(value, field.name), values)
        return
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            _collect_values(dumped, values)
