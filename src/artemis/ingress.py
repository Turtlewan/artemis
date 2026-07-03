"""Inbound owner-message routing for receiving transports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging
from typing import Protocol, runtime_checkable

from artemis.capabilities.bless import BlessStore
from artemis.capabilities.fetch_sandbox import FetchSandbox
from artemis.capabilities.invoke import (
    InvokeConfirmResult,
    InvokeState,
    build_invoke_proposal,
    confirm_invoke,
)
from artemis.capabilities.select import CapabilitySelector, SelectionResult
from artemis.intent import IntentRouter
from artemis.ports.capabilities import CapabilityStore
from artemis.ports.model import ModelPort
from artemis.ports.secrets import SecretStorePort
from artemis.ports.transport import TransportPort
from artemis.reachout.web_tool import WebTool
from artemis.transport.telegram import InboundCallback
from artemis.types import Message, OutboundMessage, Skill

_log = logging.getLogger(__name__)

_CHAT_SYSTEM = "You are Artemis, the owner's personal assistant. Answer concisely and helpfully."
_BUILD_ON_DESKTOP = (
    "I can build capabilities on the desktop — text me a question or ask me to run one instead."
)
_SAFE_ERROR = "Sorry, I couldn't handle that message safely. Please try again."
_MISSING_SECRETS = "Add the required key on the desktop, then try again."
_NOT_FOUND = "That capability is no longer available."
_RUN_ERROR = "That capability couldn't be run -- check the desktop for details."
_NO_BLESSED = "No blessed capabilities."


@runtime_checkable
class _PromptTransport(Protocol):
    async def send_prompt(
        self,
        identity: str,
        text: str,
        buttons: Sequence[Sequence[tuple[str, str]]],
    ) -> None: ...


@runtime_checkable
class _CallbackAnswerTransport(Protocol):
    async def answer_callback(self, callback_id: str) -> None: ...


@dataclass(frozen=True)
class _HeldInvoke:
    shown_version: int
    identity: str


@dataclass(frozen=True)
class _InvokeClaim:
    state: InvokeState
    held: _HeldInvoke


class InboundRouter:
    """Consume inbound transport messages and send quarantined replies."""

    def __init__(
        self,
        intent: IntentRouter,
        model: ModelPort,
        web_tool: WebTool,
        transport: TransportPort,
        owner_identity: str,
        capability_selector: CapabilitySelector | None = None,
        capability_store: CapabilityStore | None = None,
        secrets_store: SecretStorePort | None = None,
        sandbox: FetchSandbox | None = None,
        bless_store: BlessStore | None = None,
        reader: ModelPort | None = None,
        invokes: dict[str, InvokeState] | None = None,
    ) -> None:
        self._intent = intent
        self._model = model
        self._web_tool = web_tool
        self._transport = transport
        self._owner_identity = owner_identity
        self._capability_selector = capability_selector
        self._capability_store = capability_store
        self._secrets_store = secrets_store
        self._sandbox = sandbox
        self._bless_store = bless_store
        self._reader = reader or model
        self._invokes = invokes if invokes is not None else {}
        self._held_invokes: dict[str, _HeldInvoke] = {}

    async def run(self) -> None:
        """Run the inbound receive loop until the transport stream stops or the task is cancelled."""
        async for msg in self._transport.receive():
            try:
                if isinstance(msg, InboundCallback):
                    await self._handle_callback(msg)
                    continue
                reply = await self._reply(msg.text, msg.identity)
            except Exception as exc:
                _log.warning("ingress_message_degraded reason=%s", type(exc).__name__)
                reply = _SAFE_ERROR
            if reply is not None:
                await self._transport.send(
                    OutboundMessage(transport=msg.transport, identity=msg.identity, text=reply)
                )

    async def _reply(self, text: str, identity: str) -> str | None:
        if text.strip() == "/blessed":
            await self._send_blessed(identity)
            return None

        intent = await self._intent.classify(text)
        if getattr(intent, "route", None) == "invoke":
            return await self._invoke_reply(text, identity)

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

    async def _invoke_reply(self, text: str, identity: str) -> str | None:
        if not self._invoke_ready():
            return _BUILD_ON_DESKTOP

        selector = self._capability_selector
        capability_store = self._capability_store
        bless_store = self._bless_store
        if selector is None or capability_store is None or bless_store is None:
            return _BUILD_ON_DESKTOP

        selection = await selector.select(text)
        if selection.missing_required:
            return f"I need more detail to run '{selection.capability}': " + ", ".join(
                selection.missing_required
            )
        if not selection.matched or selection.capability is None:
            return _BUILD_ON_DESKTOP

        skill = capability_store.get(selection.capability)
        if skill is None:
            return _NOT_FOUND

        proposal = build_invoke_proposal(selection, skill, self._invokes, text)
        self._held_invokes[proposal.invoke_id] = _HeldInvoke(
            shown_version=skill.version,
            identity=identity,
        )
        if bless_store.is_blessed(skill.name, skill.version):
            claim = self._claim_invoke(proposal.invoke_id)
            if claim is None:
                return _NOT_FOUND
            result = await self._confirm(claim.state)
            return _safe_result_text(result)

        await self._send_consent_card(identity, proposal.invoke_id, skill, proposal.args)
        return None

    async def _handle_callback(self, callback: InboundCallback) -> None:
        if callback.data.startswith("invoke:"):
            await self._handle_invoke_callback(callback)
            return
        if callback.data.startswith("blessed:"):
            await self._handle_blessed_callback(callback)
            return
        await self._answer_callback(callback.callback_id)

    async def _handle_invoke_callback(self, callback: InboundCallback) -> None:
        parsed = _parse_invoke_callback(callback.data)
        if parsed is None:
            await self._answer_callback(callback.callback_id)
            return

        action, invoke_id = parsed
        claim = self._claim_invoke(invoke_id)
        await self._answer_callback(callback.callback_id)
        if claim is None:
            return
        if callback.identity != claim.held.identity:
            return
        if action == "cancel":
            await self._send_text(callback.identity, "Cancelled.")
            return
        if action not in {"run", "always"} or not self._invoke_ready():
            return

        capability_store = self._capability_store
        bless_store = self._bless_store
        if capability_store is None or bless_store is None:
            await self._send_text(callback.identity, _RUN_ERROR)
            return

        current = capability_store.get(claim.state.capability)
        if current is None:
            await self._send_text(callback.identity, _NOT_FOUND)
            return
        if current.version != claim.held.shown_version:
            await self._send_text(
                callback.identity,
                "This capability changed since you were asked -- here's a fresh confirmation.",
            )
            await self._send_fresh_consent(callback.identity, claim.state, current)
            return

        result = await self._confirm(claim.state)
        if action == "always" and result.status == "ok":
            bless_store.bless(current.name, current.version)
        await self._send_text(callback.identity, _safe_result_text(result))

    async def _handle_blessed_callback(self, callback: InboundCallback) -> None:
        parsed = _parse_blessed_callback(callback.data)
        await self._answer_callback(callback.callback_id)
        if parsed is None or self._bless_store is None:
            return
        self._bless_store.unbless(parsed)
        await self._send_text(callback.identity, f"Removed {parsed} from blessed capabilities.")

    async def _send_blessed(self, identity: str) -> None:
        if self._bless_store is None:
            await self._send_text(identity, _NO_BLESSED)
            return
        blessed = self._bless_store.list_blessed()
        if not blessed:
            await self._send_text(identity, _NO_BLESSED)
            return
        buttons = [[(f"Unbless {name}", f"blessed:unbless:{name}")] for name, _ in blessed]
        await self._send_prompt(identity, "Blessed capabilities:", buttons)

    async def _send_fresh_consent(
        self,
        identity: str,
        state: InvokeState,
        current: Skill,
    ) -> None:
        selection = SelectionResult(
            matched=True,
            capability=state.capability,
            args=state.args,
            confidence=1.0,
            missing_required=[],
        )
        proposal = build_invoke_proposal(selection, current, self._invokes, state.request_text)
        self._held_invokes[proposal.invoke_id] = _HeldInvoke(
            shown_version=current.version,
            identity=identity,
        )
        await self._send_consent_card(identity, proposal.invoke_id, current, proposal.args)

    async def _send_consent_card(
        self,
        identity: str,
        invoke_id: str,
        skill: Skill,
        args: dict[str, object],
    ) -> None:
        await self._send_prompt(
            identity,
            _consent_text(skill, args),
            [
                [
                    ("Run once", f"invoke:run:{invoke_id}"),
                    ("Always allow", f"invoke:always:{invoke_id}"),
                    ("Cancel", f"invoke:cancel:{invoke_id}"),
                ]
            ],
        )

    async def _send_prompt(
        self,
        identity: str,
        text: str,
        buttons: Sequence[Sequence[tuple[str, str]]],
    ) -> None:
        if isinstance(self._transport, _PromptTransport):
            await self._transport.send_prompt(identity, text, buttons)
            return
        await self._send_text(identity, text)

    async def _send_text(self, identity: str, text: str) -> None:
        await self._transport.send(
            OutboundMessage(transport=self._transport.name, identity=identity, text=text)
        )

    async def _answer_callback(self, callback_id: str) -> None:
        if isinstance(self._transport, _CallbackAnswerTransport):
            await self._transport.answer_callback(callback_id)

    def _claim_invoke(self, invoke_id: str) -> _InvokeClaim | None:
        state = self._invokes.pop(invoke_id, None)
        held = self._held_invokes.pop(invoke_id, None)
        if state is None or held is None:
            return None
        return _InvokeClaim(state=state, held=held)

    async def _confirm(self, state: InvokeState) -> InvokeConfirmResult:
        if not self._invoke_ready():
            return InvokeConfirmResult(status="error")
        assert self._capability_store is not None
        assert self._secrets_store is not None
        assert self._sandbox is not None
        return await confirm_invoke(
            state,
            capability_store=self._capability_store,
            secrets_store=self._secrets_store,
            sandbox=self._sandbox,
            reader=self._reader,
            synth=self._model,
        )

    def _invoke_ready(self) -> bool:
        return (
            self._capability_selector is not None
            and self._capability_store is not None
            and self._secrets_store is not None
            and self._sandbox is not None
            and self._bless_store is not None
        )


def _safe_result_text(result: InvokeConfirmResult) -> str:
    if result.status == "ok":
        return result.text or "The capability ran but produced no usable output."
    if result.status == "missing_secrets":
        return _MISSING_SECRETS
    if result.status == "not_found":
        return _NOT_FOUND
    return _RUN_ERROR


def _consent_text(skill: Skill, args: dict[str, object]) -> str:
    return "\n".join(
        [
            f"Capability: {skill.name}",
            f"Version: {skill.version}",
            f"Description: {skill.description}",
            "Egress domains: " + _render_list(skill.egress_domains),
            "Secret names: " + _render_list(skill.secrets),
            "Inputs: " + _render_args(args),
        ]
    )


def _render_list(values: object) -> str:
    if not isinstance(values, list) or not values:
        return "(none)"
    return ", ".join(str(value) for value in values)


def _render_args(args: dict[str, object]) -> str:
    if not args:
        return "(none)"
    return ", ".join(f"{key}={value}" for key, value in sorted(args.items()))


def _parse_invoke_callback(data: str) -> tuple[str, str] | None:
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "invoke" or not parts[2]:
        return None
    return parts[1], parts[2]


def _parse_blessed_callback(data: str) -> str | None:
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "blessed" or parts[1] != "unbless" or not parts[2]:
        return None
    return parts[2]
