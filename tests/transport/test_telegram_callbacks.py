"""Telegram inline-keyboard and callback plumbing tests."""

from __future__ import annotations

import json

import httpx

from artemis.transport.telegram import InboundCallback, TelegramTransport


async def test_send_prompt_posts_inline_keyboard_without_parse_mode() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {}})

    transport = TelegramTransport(
        "TOKEN",
        allowed_chat_ids={"42"},
        client=httpx.AsyncClient(
            base_url="https://api.telegram.org",
            transport=httpx.MockTransport(handler),
        ),
    )

    await transport.send_prompt(
        "42",
        "Capability: Demo",
        [[("Run once", "invoke:run:abc"), ("Cancel", "invoke:cancel:abc")]],
    )

    assert str(seen["url"]).endswith("/botTOKEN/sendMessage")
    assert seen["json"] == {
        "chat_id": "42",
        "text": "Capability: Demo",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Run once", "callback_data": "invoke:run:abc"},
                    {"text": "Cancel", "callback_data": "invoke:cancel:abc"},
                ]
            ]
        },
    }
    assert "parse_mode" not in seen["json"]


async def test_receive_yields_allowlisted_callback_and_drops_other_chats() -> None:
    calls = 0
    updates = [
        {
            "ok": True,
            "result": [
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "cb-spam",
                        "from": {"id": 777},
                        "message": {"chat": {"id": 99}},
                        "data": "invoke:run:spam",
                    },
                },
                {
                    "update_id": 2,
                    "callback_query": {
                        "id": "cb-ok",
                        "from": {"id": 777},
                        "message": {"chat": {"id": 42}},
                        "data": "invoke:run:abc",
                    },
                },
            ],
        },
        {"ok": True, "result": []},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        body = updates[min(calls, len(updates) - 1)]
        calls += 1
        return httpx.Response(200, json=body)

    transport = TelegramTransport(
        "TOKEN",
        allowed_chat_ids={"42"},
        client=httpx.AsyncClient(
            base_url="https://api.telegram.org",
            transport=httpx.MockTransport(handler),
        ),
        poll_timeout=0,
    )

    got = []
    async for message in transport.receive():
        got.append(message)
        break

    assert len(got) == 1
    callback = got[0]
    assert isinstance(callback, InboundCallback)
    assert callback.identity == "42"
    assert callback.callback_id == "cb-ok"
    assert callback.data == "invoke:run:abc"


async def test_answer_callback_posts_answer_callback_query() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = TelegramTransport(
        "TOKEN",
        allowed_chat_ids={"42"},
        client=httpx.AsyncClient(
            base_url="https://api.telegram.org",
            transport=httpx.MockTransport(handler),
        ),
    )

    await transport.answer_callback("callback-id")

    assert str(seen["url"]).endswith("/botTOKEN/answerCallbackQuery")
    assert seen["json"] == {"callback_query_id": "callback-id"}
