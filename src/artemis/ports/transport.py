"""Transport port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from artemis.types import InboundMessage, OutboundMessage


@runtime_checkable
class TransportPort(Protocol):
    name: str

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Ingress stream; identity resolved per transport (allowlist/session)."""
        ...

    async def send(self, msg: OutboundMessage) -> None:
        """Egress, including proactive push."""
        ...
