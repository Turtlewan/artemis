"""Tests for inbound transport routing."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import cast

import pytest

from artemis import app as app_module
from artemis.app import App, build_app
from artemis.ingress import InboundRouter
from artemis.intent import Intent, IntentRouter, Route
from artemis.ports.transport import TransportPort
from artemis.proactivity import ProactiveWorker
from artemis.reachout.web_tool import WebAnswer, WebTool
from artemis.scheduler import DurableScheduler
from artemis.transport import ConsoleTransport
from artemis.types import InboundMessage, Message, ModelResponse, OutboundMessage, Usage


class FakeTransport:
    name = "fake"

    def __init__(self, messages: list[InboundMessage]) -> None:
        self._messages = messages
        self.sent: list[OutboundMessage] = []

    def receive(self) -> AsyncIterator[InboundMessage]:
        async def _gen() -> AsyncIterator[InboundMessage]:
            for msg in self._messages:
                yield msg

        return _gen()

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


class FakeModel:
    def __init__(self, text: str = "model answer", *, raises_on: set[str] | None = None) -> None:
        self._text = text
        self._raises_on = raises_on or set()
        self.prompts: list[str] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del model, response_schema, temperature, max_tokens
        prompt = messages[-1].content
        self.prompts.append(prompt)
        if prompt in self._raises_on:
            raise RuntimeError("model failed")
        return ModelResponse(
            text=self._text,
            model_id="fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FixedIntentRouter(IntentRouter):
    def __init__(self, routes: dict[str, Route]) -> None:
        self._routes = routes

    async def classify(self, text: str) -> Intent:
        return Intent(route=self._routes[text], confidence=1.0, reason="test")


class FakeWebTool:
    def __init__(self, text: str = "web answer") -> None:
        self._text = text
        self.queries: list[str] = []

    async def answer(self, query: str) -> WebAnswer:
        self.queries.append(query)
        return WebAnswer(answer=self._text, sources=[])


class FakeScheduler:
    def __init__(self) -> None:
        self.ran = False

    async def run(self) -> None:
        self.ran = True


class FakeIngress:
    def __init__(self) -> None:
        self.ran = False

    async def run(self) -> None:
        self.ran = True


def _inbound(text: str, *, identity: str = "owner") -> InboundMessage:
    return InboundMessage(transport="fake", identity=identity, text=text)


def _router(
    *,
    routes: dict[str, Route],
    transport: FakeTransport,
    model: FakeModel | None = None,
    web_tool: FakeWebTool | None = None,
) -> InboundRouter:
    return InboundRouter(
        intent=FixedIntentRouter(routes),
        model=model or FakeModel(),
        web_tool=cast(WebTool, web_tool or FakeWebTool()),
        transport=transport,
        owner_identity="owner",
    )


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        ("plain_ask", "model answer"),
        ("web_q", "web answer"),
        (
            "build",
            "I can build capabilities on the desktop — text me a question or ask me to run one "
            "instead.",
        ),
    ],
)
async def test_inbound_router_replies_for_supported_routes(route: Route, expected: str) -> None:
    transport = FakeTransport([_inbound("question")])
    web_tool = FakeWebTool()

    await _router(routes={"question": route}, transport=transport, web_tool=web_tool).run()

    assert [msg.text for msg in transport.sent] == [expected]
    assert [msg.identity for msg in transport.sent] == ["owner"]
    if route == "web_q":
        assert web_tool.queries == ["question"]


async def test_inbound_router_treats_aggregate_as_web_q() -> None:
    transport = FakeTransport([_inbound("research")])
    web_tool = FakeWebTool("aggregate answer")

    await _router(routes={"research": "aggregate"}, transport=transport, web_tool=web_tool).run()

    assert [msg.text for msg in transport.sent] == ["aggregate answer"]
    assert web_tool.queries == ["research"]


async def test_inbound_router_degrades_one_message_and_continues() -> None:
    transport = FakeTransport([_inbound("bad"), _inbound("good")])
    model = FakeModel("ok", raises_on={"bad"})

    await _router(
        routes={"bad": "plain_ask", "good": "plain_ask"},
        transport=transport,
        model=model,
    ).run()

    assert [msg.text for msg in transport.sent] == [
        "Sorry, I couldn't handle that message safely. Please try again.",
        "ok",
    ]


def test_build_app_leaves_console_without_ingress() -> None:
    app = build_app(model=FakeModel(), transport=ConsoleTransport())

    assert app.ingress is None


def test_build_app_wires_ingress_for_receiving_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    def build_fake_web_tool(*, tavily_api_key: str) -> WebTool:
        assert tavily_api_key == ""
        return cast(WebTool, FakeWebTool())

    monkeypatch.setattr(app_module, "build_web_tool", build_fake_web_tool)
    app = build_app(model=FakeModel(), transport=cast(TransportPort, FakeTransport([])))

    assert app.ingress is not None


async def test_app_run_drives_scheduler_and_ingress() -> None:
    scheduler = FakeScheduler()
    ingress = FakeIngress()
    app = App(
        scheduler=cast(DurableScheduler, scheduler),
        worker=cast(ProactiveWorker, object()),
        ingress=cast(InboundRouter, ingress),
    )

    await app.run()

    assert scheduler.ran is True
    assert ingress.ran is True
