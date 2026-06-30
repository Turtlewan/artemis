"""Console transport: render outbound messages to stdout (dev/fallback surface)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from artemis.types import InboundMessage, OutboundMessage


class ConsoleTransport:
    name = "console"

    def __init__(self, *, write: Callable[[str], None] = print) -> None:
        self._write = write

    def receive(self) -> AsyncIterator[InboundMessage]:
        async def _empty() -> AsyncIterator[InboundMessage]:
            return
            yield  # pragma: no cover

        return _empty()

    async def send(self, msg: OutboundMessage) -> None:
        tag = "[proactive]" if msg.proactive else "[reply]"
        self._write(f"{tag} -> {msg.identity}: {msg.text}")
