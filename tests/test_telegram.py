"""Hermetic tests for the Telegram transport (httpx.MockTransport, no network)."""

from __future__ import annotations

import json

import httpx

from artemis.ports.transport import TransportPort
from artemis.transport.telegram import TelegramTransport, telegram_from_env
from artemis.types import OutboundMessage


def test_satisfies_port() -> None:
    assert isinstance(TelegramTransport("T", allowed_chat_ids=set()), TransportPort)


async def test_send_posts_sendmessage() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {}})

    t = TelegramTransport(
        "TOKEN",
        allowed_chat_ids={"42"},
        client=httpx.AsyncClient(
            base_url="https://api.telegram.org", transport=httpx.MockTransport(handler)
        ),
    )
    await t.send(OutboundMessage(transport="telegram", identity="42", text="hi", proactive=True))
    assert str(seen["url"]).endswith("/botTOKEN/sendMessage")
    assert seen["json"] == {"chat_id": "42", "text": "hi"}


async def test_receive_yields_allowed_skips_others() -> None:
    updates = {
        "ok": True,
        "result": [
            {"update_id": 1, "message": {"chat": {"id": 42}, "text": "hello"}},
            {"update_id": 2, "message": {"chat": {"id": 99}, "text": "spam"}},
            {"update_id": 3, "message": {"chat": {"id": 42}, "text": "again"}},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=updates)

    t = TelegramTransport(
        "TOKEN",
        allowed_chat_ids={"42"},
        client=httpx.AsyncClient(
            base_url="https://api.telegram.org", transport=httpx.MockTransport(handler)
        ),
        poll_timeout=0,
    )
    got = []
    async for msg in t.receive():
        got.append(msg)
        if len(got) == 2:
            break
    assert [m.text for m in got] == ["hello", "again"]
    assert all(m.identity == "42" and m.transport == "telegram" for m in got)


def test_from_env_none_without_token() -> None:
    assert telegram_from_env({}) is None


def test_from_env_builds_with_allowlist() -> None:
    t = telegram_from_env({"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_IDS": "1, 2 ,3"})
    assert isinstance(t, TelegramTransport)
    assert t.allowed_chat_ids == {"1", "2", "3"}
