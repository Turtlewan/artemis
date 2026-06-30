---
slice: 3
status: ready
coder_effort: medium
---

# v2-16 — Telegram transport (proactive push reaches the phone)

**Identity:** Fourth Slice-3 spec — a real remote `TransportPort` over the Telegram Bot API so proactive pushes leave the box and arrive on mobile. `send` → `sendMessage`; `receive` → long-poll `getUpdates` filtered by a chat-ID allowlist. Drops into the existing `build_app(transport=...)` seam; `main()` env-selects Telegram when configured, else falls back to the console transport. Uses `httpx` (already a core dep) and is fully hermetically testable via `httpx.MockTransport`.

Architecture §7 honored: identity = **chat-ID allowlist** (inbound from non-allowlisted chats is dropped); the bot token is a secret. **Stopgap:** the token is read from an env var for now — the keychain home for secrets (architecture §7) doesn't exist yet; noted as a follow-up. Per the §7 caveat, Telegram messages transit Telegram's servers (acceptable post-privacy-wall).

## Files to change

1. `src/artemis/transport/telegram.py` — **create**: `TelegramTransport` + `telegram_from_env`.
2. `src/artemis/transport/__init__.py` — **modify**: export the new names.
3. `src/artemis/app.py` — **modify**: `main()` env-selects Telegram vs console.
4. `tests/test_telegram.py` — **create**: hermetic send/receive/allowlist/from_env tests.

One cohesive "Telegram surface" vertical → a single logical phase.

## Exact changes

### 1. `src/artemis/transport/telegram.py`

`send` and `receive` follow the `ConsoleTransport` pattern (`receive` is a plain method returning an inner async generator, matching the port). The HTTP client is injectable for hermetic tests; the default targets the real Telegram API.

```python
"""Telegram bot transport over the Bot API (proactive push + allowlisted ingress)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping

import httpx

from artemis.types import InboundMessage, OutboundMessage

_API_BASE = "https://api.telegram.org"


class TelegramTransport:
    name = "telegram"

    def __init__(
        self,
        token: str,
        *,
        allowed_chat_ids: set[str],
        client: httpx.AsyncClient | None = None,
        poll_timeout: int = 30,
    ) -> None:
        self._token = token
        self.allowed_chat_ids = allowed_chat_ids
        self._client = client or httpx.AsyncClient(base_url=_API_BASE)
        self._poll_timeout = poll_timeout
        self._offset = 0

    def _method(self, name: str) -> str:
        return f"/bot{self._token}/{name}"

    async def send(self, msg: OutboundMessage) -> None:
        resp = await self._client.post(
            self._method("sendMessage"),
            json={"chat_id": msg.identity, "text": msg.text},
        )
        resp.raise_for_status()

    def receive(self) -> AsyncIterator[InboundMessage]:
        async def _gen() -> AsyncIterator[InboundMessage]:
            while True:
                resp = await self._client.get(
                    self._method("getUpdates"),
                    params={"offset": self._offset, "timeout": self._poll_timeout},
                )
                resp.raise_for_status()
                for update in resp.json().get("result", []):
                    self._offset = update["update_id"] + 1
                    message = update.get("message")
                    if message is None:
                        continue
                    chat_id = str(message["chat"]["id"])
                    text = message.get("text")
                    if text is None or chat_id not in self.allowed_chat_ids:
                        continue  # non-text or non-allowlisted -> drop
                    yield InboundMessage(transport="telegram", identity=chat_id, text=text)

        return _gen()


def telegram_from_env(env: Mapping[str, str] = os.environ) -> TelegramTransport | None:
    """Build a TelegramTransport from env, or None if TELEGRAM_BOT_TOKEN is unset.

    TELEGRAM_BOT_TOKEN  - bot token (stopgap for a future keychain secret)
    TELEGRAM_CHAT_IDS   - comma-separated allowlist of chat IDs for ingress
    """
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    allowed = {c.strip() for c in env.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()}
    return TelegramTransport(token, allowed_chat_ids=allowed)
```

### 2. `src/artemis/transport/__init__.py`

```python
"""Transport adapters (egress/ingress surfaces) behind TransportPort."""

from __future__ import annotations

from artemis.transport.console import ConsoleTransport
from artemis.transport.telegram import TelegramTransport, telegram_from_env

__all__ = ["ConsoleTransport", "TelegramTransport", "telegram_from_env"]
```

### 3. `src/artemis/app.py` — `main()` only

Replace the body of `main()` to env-select the transport. Add the import. Leave `App` / `build_app` unchanged.

New import (with the other `artemis.transport` import):
```python
from artemis.transport import ConsoleTransport, telegram_from_env
```
(If `app.py` does not already import `ConsoleTransport` at module top, keep its existing import as-is — `build_app` references it; just add `telegram_from_env`.)

New `main()`:
```python
def main() -> None:
    """Console-script entry: run the loop. Pushes to Telegram if configured, else the console."""
    db_path = os.environ.get("ARTEMIS_DB", "scheduler.db")
    telegram = telegram_from_env(os.environ)
    if telegram is not None:
        owner_identity = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
        app = build_app(db_path=db_path, transport=telegram, owner_identity=owner_identity)
    else:
        app = build_app(db_path=db_path)
    asyncio.run(app.run())
```

### 4. `tests/test_telegram.py`

```python
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
        "TOKEN", allowed_chat_ids={"42"}, client=httpx.AsyncClient(
            base_url="https://api.telegram.org", transport=httpx.MockTransport(handler)
        )
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
```

Notes for the coder:
- Each test inlines `httpx.AsyncClient(base_url="https://api.telegram.org", transport=httpx.MockTransport(handler))`; the handler is `Callable[[httpx.Request], httpx.Response]`.
- `receive()`'s generator polls forever; the test breaks out after the expected count (the mock returns enough allowed updates in one batch, so no second poll happens). Do not add a stop flag to the production code for the test's sake.
- Client lifecycle is intentionally unmanaged (the app runs until process exit). Do not add `aclose()`/context-manager plumbing in this spec.

## Acceptance criteria

1. `TelegramTransport` structurally satisfies `TransportPort` → `test_satisfies_port` passes.
2. `send` POSTs `sendMessage` with `{chat_id, text}` to `/bot<token>/sendMessage` → `test_send_posts_sendmessage` passes.
3. `receive` yields `InboundMessage` for allowlisted chats and **drops non-allowlisted + non-text** updates → `test_receive_yields_allowed_skips_others` passes.
4. `telegram_from_env` returns `None` without a token and builds a parsed allowlist with one → `test_from_env_*` pass.
5. `main()` uses Telegram when `TELEGRAM_BOT_TOKEN` is set, else console (verified by code review + mypy; not a runtime test — it starts the forever-loop).
6. Full-project verify green: `uv run mypy` (strict) + `uv run pytest -q` + `uv run ruff check` + `uv run ruff format --check` clean.

## Commands to run

```bash
uv run ruff format src/artemis/transport src/artemis/app.py tests/test_telegram.py
uv run ruff check src/artemis/transport src/artemis/app.py tests/test_telegram.py
uv run mypy
uv run pytest -q
```
