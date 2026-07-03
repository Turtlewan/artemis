"""Tests for Telegram invoke consent gating in ingress."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from artemis import ingress as ingress_module
from artemis.capabilities.bless import BlessStore
from artemis.capabilities.fetch_sandbox import FetchSandbox
from artemis.capabilities.invoke import InvokeConfirmResult, InvokeState
from artemis.capabilities.select import CapabilitySelector, SelectionResult
from artemis.ingress import InboundRouter
from artemis.intent import Intent, IntentRouter
from artemis.ports.capabilities import CapabilityStore
from artemis.ports.model import ModelPort
from artemis.ports.secrets import SecretStorePort
from artemis.reachout.web_tool import WebTool
from artemis.transport.telegram import InboundCallback
from artemis.types import (
    InboundMessage,
    Message,
    ModelResponse,
    OutboundMessage,
    Skill,
    SkillInputParam,
    Usage,
)


@dataclass
class Prompt:
    identity: str
    text: str
    buttons: Sequence[Sequence[tuple[str, str]]]


class FakeTransport:
    name = "telegram"

    def __init__(self, messages: list[InboundMessage]) -> None:
        self.messages = messages
        self.sent: list[OutboundMessage] = []
        self.prompts: list[Prompt] = []
        self.answered: list[str] = []

    def receive(self) -> AsyncIterator[InboundMessage]:
        async def _gen() -> AsyncIterator[InboundMessage]:
            while self.messages:
                yield self.messages.pop(0)

        return _gen()

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)

    async def send_prompt(
        self,
        identity: str,
        text: str,
        buttons: Sequence[Sequence[tuple[str, str]]],
    ) -> None:
        self.prompts.append(Prompt(identity=identity, text=text, buttons=buttons))

    async def answer_callback(self, callback_id: str) -> None:
        self.answered.append(callback_id)


class FixedIntentRouter:
    async def classify(self, text: str) -> Intent:
        del text
        return cast(Intent, SimpleNamespace(route="invoke"))


class FakeModel:
    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, model, response_schema, temperature, max_tokens
        return ModelResponse(
            text="model",
            model_id="fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FakeWebTool:
    pass


class FakeSelector:
    def __init__(self, selection: SelectionResult) -> None:
        self._selection = selection
        self.requests: list[str] = []

    async def select(self, request: str) -> SelectionResult:
        self.requests.append(request)
        return self._selection


class FakeCapabilityStore:
    def __init__(self, skill: Skill | None) -> None:
        self.skill = skill

    def get(self, name: str) -> Skill | None:
        if self.skill is None or self.skill.name != name:
            return None
        return self.skill


class FakeSecrets:
    def get(self, name: str) -> str | None:
        return {"API_KEY": "secret-value"}.get(name)

    def set(self, name: str, value: str) -> None:
        del name, value

    def delete(self, name: str) -> None:
        del name

    def list_names(self) -> list[str]:
        return ["API_KEY"]


def _skill(*, version: int = 1) -> Skill:
    return Skill(
        name="gmail-reader",
        description="Read recent Gmail messages",
        version=version,
        path="C:/tmp/gmail-reader",
        tags=[],
        uses=[],
        secrets=["API_KEY"],
        inputs=[SkillInputParam(name="query", type="string", description="Search query")],
        egress_domains=["api.example.com"],
    )


def _selection() -> SelectionResult:
    return SelectionResult(
        matched=True,
        capability="gmail-reader",
        args={"query": "hello"},
        confidence=0.99,
        missing_required=[],
    )


def _message(text: str = "run gmail") -> InboundMessage:
    return InboundMessage(transport="telegram", identity="42", text=text)


def _callback(data: str, *, callback_id: str = "cb") -> InboundCallback:
    return InboundCallback(
        transport="telegram",
        identity="42",
        text="",
        data=data,
        callback_id=callback_id,
    )


def _button_data(prompt: Prompt, label: str) -> str:
    for row in prompt.buttons:
        for button_label, data in row:
            if button_label == label:
                return data
    raise AssertionError(f"button not found: {label}")


def _router(
    *,
    transport: FakeTransport,
    store: FakeCapabilityStore,
    bless_store: BlessStore,
    selector: FakeSelector | None = None,
) -> InboundRouter:
    return InboundRouter(
        intent=cast(IntentRouter, FixedIntentRouter()),
        model=cast(ModelPort, FakeModel()),
        web_tool=cast(WebTool, FakeWebTool()),
        transport=transport,
        owner_identity="42",
        capability_selector=cast(CapabilitySelector, selector or FakeSelector(_selection())),
        capability_store=cast(CapabilityStore, store),
        secrets_store=cast(SecretStorePort, FakeSecrets()),
        sandbox=cast(FetchSandbox, object()),
        bless_store=bless_store,
        reader=cast(ModelPort, FakeModel()),
    )


def _install_confirm(
    monkeypatch: pytest.MonkeyPatch,
    results: list[InvokeConfirmResult],
) -> list[InvokeState]:
    calls: list[InvokeState] = []

    async def fake_confirm(
        state: InvokeState,
        *,
        capability_store: CapabilityStore,
        secrets_store: SecretStorePort,
        sandbox: FetchSandbox,
        reader: ModelPort,
        synth: ModelPort,
    ) -> InvokeConfirmResult:
        del capability_store, secrets_store, sandbox, reader, synth
        calls.append(state)
        return results.pop(0)

    monkeypatch.setattr(ingress_module, "confirm_invoke", fake_confirm)
    return calls


async def test_blessed_capability_auto_runs_without_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_confirm(monkeypatch, [InvokeConfirmResult(status="ok", text="safe output")])
    bless_store = BlessStore(tmp_path)
    bless_store.bless("gmail-reader", 1)
    transport = FakeTransport([_message()])

    await _router(
        transport=transport, store=FakeCapabilityStore(_skill()), bless_store=bless_store
    ).run()

    assert len(calls) == 1
    assert transport.prompts == []
    assert [msg.text for msg in transport.sent] == ["safe output"]


async def test_unblessed_invoke_sends_plain_consent_card_and_does_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_confirm(monkeypatch, [InvokeConfirmResult(status="ok", text="safe output")])
    transport = FakeTransport([_message()])

    await _router(
        transport=transport,
        store=FakeCapabilityStore(_skill()),
        bless_store=BlessStore(tmp_path),
    ).run()

    assert calls == []
    assert transport.sent == []
    assert len(transport.prompts) == 1
    prompt = transport.prompts[0]
    assert "Capability: gmail-reader" in prompt.text
    assert "api.example.com" in prompt.text
    assert "API_KEY" in prompt.text
    assert "secret-value" not in prompt.text
    assert "query=hello" in prompt.text
    assert _button_data(prompt, "Run once").startswith("invoke:run:")
    assert _button_data(prompt, "Always allow").startswith("invoke:always:")
    assert _button_data(prompt, "Cancel").startswith("invoke:cancel:")


async def test_run_once_callback_runs_once_without_blessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_confirm(monkeypatch, [InvokeConfirmResult(status="ok", text="safe output")])
    bless_store = BlessStore(tmp_path)
    transport = FakeTransport([_message()])
    router = _router(
        transport=transport,
        store=FakeCapabilityStore(_skill()),
        bless_store=bless_store,
    )
    await router.run()
    data = _button_data(transport.prompts[0], "Run once")

    transport.messages = [_callback(data, callback_id="first")]
    await router.run()
    transport.messages = [_callback(data, callback_id="replay")]
    await router.run()

    assert len(calls) == 1
    assert [msg.text for msg in transport.sent] == ["safe output"]
    assert transport.answered == ["first", "replay"]
    assert bless_store.is_blessed("gmail-reader", 1) is False


async def test_always_allow_blesses_only_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_confirm(monkeypatch, [InvokeConfirmResult(status="ok", text="safe output")])
    bless_store = BlessStore(tmp_path)
    transport = FakeTransport([_message()])
    router = _router(
        transport=transport,
        store=FakeCapabilityStore(_skill()),
        bless_store=bless_store,
    )
    await router.run()

    transport.messages = [_callback(_button_data(transport.prompts[0], "Always allow"))]
    await router.run()

    assert bless_store.is_blessed("gmail-reader", 1) is True


async def test_always_allow_error_is_generic_and_does_not_bless(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_confirm(
        monkeypatch,
        [InvokeConfirmResult(status="error", text="stack trace secret-value raw output")],
    )
    bless_store = BlessStore(tmp_path)
    transport = FakeTransport([_message()])
    router = _router(
        transport=transport,
        store=FakeCapabilityStore(_skill()),
        bless_store=bless_store,
    )
    await router.run()

    transport.messages = [_callback(_button_data(transport.prompts[0], "Always allow"))]
    await router.run()

    assert [msg.text for msg in transport.sent] == [
        "That capability couldn't be run -- check the desktop for details."
    ]
    assert "secret-value" not in transport.sent[0].text
    assert "raw output" not in transport.sent[0].text
    assert bless_store.is_blessed("gmail-reader", 1) is False


async def test_not_found_reply_is_generic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_confirm(monkeypatch, [InvokeConfirmResult(status="not_found", text="internal detail")])
    transport = FakeTransport([_message()])
    router = _router(
        transport=transport,
        store=FakeCapabilityStore(_skill()),
        bless_store=BlessStore(tmp_path),
    )
    await router.run()

    transport.messages = [_callback(_button_data(transport.prompts[0], "Run once"))]
    await router.run()

    assert [msg.text for msg in transport.sent] == ["That capability is no longer available."]
    assert "internal detail" not in transport.sent[0].text


async def test_stale_version_callback_recards_without_running_or_blessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_confirm(monkeypatch, [InvokeConfirmResult(status="ok", text="safe output")])
    bless_store = BlessStore(tmp_path)
    store = FakeCapabilityStore(_skill(version=1))
    transport = FakeTransport([_message()])
    router = _router(transport=transport, store=store, bless_store=bless_store)
    await router.run()
    old_run = _button_data(transport.prompts[0], "Run once")

    store.skill = _skill(version=2)
    transport.messages = [_callback(old_run)]
    await router.run()

    assert calls == []
    assert bless_store.is_blessed("gmail-reader", 2) is False
    assert [msg.text for msg in transport.sent] == [
        "This capability changed since you were asked -- here's a fresh confirmation."
    ]
    assert len(transport.prompts) == 2
    assert "Version: 2" in transport.prompts[1].text


async def test_cancel_callback_pops_without_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_confirm(monkeypatch, [InvokeConfirmResult(status="ok", text="safe output")])
    transport = FakeTransport([_message()])
    router = _router(
        transport=transport,
        store=FakeCapabilityStore(_skill()),
        bless_store=BlessStore(tmp_path),
    )
    await router.run()
    data = _button_data(transport.prompts[0], "Cancel")

    transport.messages = [_callback(data), _callback(data, callback_id="replay")]
    await router.run()

    assert calls == []
    assert [msg.text for msg in transport.sent] == ["Cancelled."]


async def test_blessed_command_lists_and_unblesses(tmp_path: Path) -> None:
    bless_store = BlessStore(tmp_path)
    bless_store.bless("gmail-reader", 1)
    transport = FakeTransport([_message("/blessed")])
    router = _router(
        transport=transport,
        store=FakeCapabilityStore(_skill()),
        bless_store=bless_store,
    )
    await router.run()

    assert len(transport.prompts) == 1
    assert transport.prompts[0].text == "Blessed capabilities:"
    data = _button_data(transport.prompts[0], "Unbless gmail-reader")

    transport.messages = [_callback(data)]
    await router.run()

    assert bless_store.is_blessed("gmail-reader", 1) is False
    assert [msg.text for msg in transport.sent] == [
        "Removed gmail-reader from blessed capabilities."
    ]
