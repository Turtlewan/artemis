from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Literal

import pytest

from artemis.config import Settings
from artemis.dev import email_rules
from artemis.dev.email_rules import DevRulesRuntime, poll_once
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.gmail.client import GMAIL_READONLY_SCOPE
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector
from artemis.reactions import compose as compose_module
from artemis.runtime_config import ReactionConfig, RuntimeConfig

KEY = b"8" * 32


class FakeGmailApiPort:
    def __init__(self, messages: Mapping[str, str]) -> None:
        self.messages = dict(messages)
        self.list_calls: list[tuple[str, str | None]] = []
        self.get_calls: list[str] = []

    def list_message_ids(self, *, q: str, page_token: str | None) -> tuple[list[str], str | None]:
        self.list_calls.append((q, page_token))
        return list(self.messages), None

    def get_message(
        self, message_id: str, *, fmt: Literal["full", "metadata"]
    ) -> Mapping[str, object]:
        self.get_calls.append(message_id)
        return {
            "id": message_id,
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": _b64(self.messages[message_id])},
            },
        }

    def list_history(
        self, *, start_history_id: str, page_token: str | None
    ) -> tuple[list[Mapping[str, object]], str | None, str]:
        del start_history_id, page_token
        return [], None, "1"

    def get_attachment(self, *, message_id: str, attachment_id: str) -> bytes:
        del message_id, attachment_id
        return b""

    def current_history_id(self) -> str:
        return "1"

    def get_thread(self, thread_id: str) -> Mapping[str, object]:
        return {"id": thread_id}

    def list_threads(self, *, q: str, page_token: str | None) -> tuple[list[str], str | None]:
        del q, page_token
        return [], None


class FakeLocalModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del response_schema, temperature, max_tokens
        text = messages[-1].content
        self.calls.append((role, text))
        if "commitment-body" in text:
            payload = _quarantine("Please send the report tomorrow.")
        elif "flight-body" in text:
            payload = _quarantine("Flight SQ1 from Singapore to Tokyo.")
        elif "gift-body" in text:
            payload = _quarantine("Taylor would like a fountain pen.")
        elif "nothing-body" in text:
            payload = _quarantine("Newsletter digest.")
        elif "Please send the report" in text:
            payload = {"has_commitment": True}
        elif "Flight SQ1" in text:
            payload = {
                "has_event": True,
                "event_kind": "flight",
                "title": "Flight SQ1",
                "start_datetime": "2026-07-01T08:00:00Z",
                "end_datetime": "2026-07-01T15:00:00Z",
                "origin": "Singapore",
                "destination": "Tokyo",
                "confirmation_ref": "ABC123",
                "co_travellers": ["Ashley"],
            }
        elif "fountain pen" in text:
            payload = {
                "has_gift_signal": True,
                "gift_item": "fountain pen",
                "gift_recipient": "Taylor",
            }
        elif "Newsletter digest" in text:
            payload = {}
        else:
            raise AssertionError(f"unexpected model input: {text}")
        return ModelResponse(
            text=json.dumps(payload),
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            origin="local",
            model_id="fake-local",
        )

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature
        return _empty_stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[1.0] for _ in texts]


class ToolCapableModel(FakeLocalModel):
    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: object | None = None,
    ) -> ModelResponse:
        del tools
        return await super().complete(
            role=role,
            messages=messages,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )


@pytest.mark.asyncio
async def test_poll_once_observe_logs_structured_extracts_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        compose_module,
        "get_runtime_config",
        lambda: RuntimeConfig(reaction=ReactionConfig(reactions_mode="observe")),
    )
    runtime, gmail, model, would_log, structured_log = _runtime(tmp_path)

    count = await poll_once(runtime)

    assert count == 4
    assert gmail.get_calls == ["commitment", "flight", "gift", "nothing"]
    assert len(model.calls) == 8
    assert all(role == "responder" for role, _text in model.calls)
    assert all("raw body" not in line for line in _lines(would_log))
    # No raw body of ANY of the four canned emails may reach the structured log
    # (security invariant: only laundered content is persisted; harness review).
    for sentinel in ("raw body", "commitment-body", "flight-body", "gift-body", "nothing-body"):
        assert all(sentinel not in line for line in _lines(structured_log))

    records = [json.loads(line) for line in _lines(structured_log)]
    assert [record["extract"]["source_ref"] for record in records] == [
        "gmail:commitment",
        "gmail:flight",
        "gmail:gift",
        "gmail:nothing",
    ]
    by_ref = {record["extract"]["source_ref"]: record["extract"] for record in records}
    assert by_ref["gmail:commitment"]["has_commitment"] is True
    assert by_ref["gmail:flight"]["has_event"] is True
    assert by_ref["gmail:flight"]["event_kind"] == "flight"
    assert by_ref["gmail:gift"]["has_gift_signal"] is True
    assert by_ref["gmail:nothing"]["has_commitment"] is False
    assert by_ref["gmail:nothing"]["has_event"] is False
    assert by_ref["gmail:nothing"]["has_gift_signal"] is False

    notices = [json.loads(line)["notice"] for line in _lines(would_log)]
    assert "WOULD suggest: reaction:email_to_task" in notices
    assert "WOULD execute: reaction:email_to_held_event" in notices
    assert "WOULD execute: reaction:gift_signal" in notices
    assert len(notices) == 3

    second = await poll_once(runtime)

    assert second == 0
    assert gmail.get_calls == ["commitment", "flight", "gift", "nothing"]
    assert len(_lines(structured_log)) == 4
    assert runtime.scope == GMAIL_READONLY_SCOPE


def test_build_runtime_refuses_live_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        compose_module,
        "get_runtime_config",
        lambda: RuntimeConfig(reaction=ReactionConfig(reactions_mode="live")),
    )
    with pytest.raises(RuntimeError, match="observe"):
        email_rules.build_dev_rules_runtime(
            settings=Settings(data_root=tmp_path),
            key_provider=FakeKeyProvider({OWNER_PRIVATE: KEY}, owner_unlocked=True),
            gmail=FakeGmailApiPort({}),
            model=FakeLocalModel(),
        )


def test_build_runtime_rejects_tool_capable_reader_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        compose_module,
        "get_runtime_config",
        lambda: RuntimeConfig(reaction=ReactionConfig(reactions_mode="observe")),
    )
    with pytest.raises(RuntimeError, match="toolless"):
        email_rules.build_dev_rules_runtime(
            settings=Settings(data_root=tmp_path),
            key_provider=FakeKeyProvider({OWNER_PRIVATE: KEY}, owner_unlocked=True),
            gmail=FakeGmailApiPort({}),
            model=ToolCapableModel(),
        )


def _runtime(
    tmp_path: Path,
) -> tuple[DevRulesRuntime, FakeGmailApiPort, FakeLocalModel, Path, Path]:
    settings = Settings(data_root=tmp_path)
    key_provider = FakeKeyProvider({OWNER_PRIVATE: KEY}, owner_unlocked=True)
    gmail = FakeGmailApiPort(
        {
            "commitment": "commitment-body raw body secret",
            "flight": "flight-body raw body secret",
            "gift": "gift-body raw body secret",
            "nothing": "nothing-body raw body secret",
        }
    )
    model = FakeLocalModel()
    runtime = email_rules.build_dev_rules_runtime(
        settings=settings,
        key_provider=key_provider,
        gmail=gmail,
        model=model,
    )
    log_dir = tmp_path / "dev" / OWNER_PRIVATE / "dev" / "email_rules"
    return runtime, gmail, model, log_dir / "would.jsonl", log_dir / "structured_extracts.jsonl"


def _quarantine(summary: str) -> dict[str, object]:
    return {"summary": summary, "claims": [], "flagged_injection": False}


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


async def _empty_stream() -> AsyncIterator[str]:
    if False:
        yield ""
