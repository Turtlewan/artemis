"""Inbound owner-message routing for receiving transports."""

from __future__ import annotations

import logging

from artemis.intent import IntentRouter
from artemis.ports.model import ModelPort
from artemis.ports.transport import TransportPort
from artemis.reachout.web_tool import WebTool
from artemis.types import Message, OutboundMessage

_log = logging.getLogger(__name__)

_CHAT_SYSTEM = "You are Artemis, the owner's personal assistant. Answer concisely and helpfully."
_BUILD_ON_DESKTOP = (
    "I can build capabilities on the desktop — text me a question or ask me to run one instead."
)
_SAFE_ERROR = "Sorry, I couldn't handle that message safely. Please try again."


class InboundRouter:
    """Consume inbound transport messages and send quarantined replies."""

    def __init__(
        self,
        intent: IntentRouter,
        model: ModelPort,
        web_tool: WebTool,
        transport: TransportPort,
        owner_identity: str,
    ) -> None:
        self._intent = intent
        self._model = model
        self._web_tool = web_tool
        self._transport = transport
        self._owner_identity = owner_identity

    async def run(self) -> None:
        """Run the inbound receive loop until the transport stream stops or the task is cancelled."""
        async for msg in self._transport.receive():
            try:
                reply = await self._reply(msg.text)
            except Exception as exc:
                _log.warning("ingress_message_degraded reason=%s", type(exc).__name__)
                reply = _SAFE_ERROR
            await self._transport.send(
                OutboundMessage(transport=msg.transport, identity=msg.identity, text=reply)
            )

    async def _reply(self, text: str) -> str:
        intent = await self._intent.classify(text)
        if intent.route == "plain_ask":
            response = await self._model.complete(
                messages=[
                    Message(role="system", content=_CHAT_SYSTEM),
                    Message(role="user", content=text),
                ]
            )
            return response.text

        if intent.route in {"web_q", "aggregate"}:
            answer = await self._web_tool.answer(text)
            return answer.answer

        return _BUILD_ON_DESKTOP
