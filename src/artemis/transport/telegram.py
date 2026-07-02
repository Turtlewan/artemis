"""Telegram bot transport over the Bot API (proactive push + allowlisted ingress)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping

import httpx

from artemis.ports.secrets import SecretStorePort
from artemis.secrets_store import resolve_secret
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


def telegram_from_env(
    env: Mapping[str, str] = os.environ,
    *,
    secrets: SecretStorePort | None = None,
) -> TelegramTransport | None:
    """Build a TelegramTransport, or None if no bot token is configured.

    TELEGRAM_BOT_TOKEN  - bot token: resolved keychain-first (when `secrets` is
                          given), then env fallback (migration path off the env stopgap).
    TELEGRAM_CHAT_IDS   - comma-separated allowlist of chat IDs (config, stays env).
    """
    token = resolve_secret("TELEGRAM_BOT_TOKEN", secrets=secrets, env=env)
    if not token:
        return None
    allowed = {c.strip() for c in env.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()}
    return TelegramTransport(token, allowed_chat_ids=allowed)
