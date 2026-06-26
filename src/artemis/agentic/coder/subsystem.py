"""Embedded OpenHands coding subsystem behind Artemis-owned seams.

Artemis owns planner, router, authority, inbox, and the sandbox guard. OpenHands
is only the coding executor, reached through a small adapter so tests can run
without live SDK calls or network.
"""

from __future__ import annotations

import inspect
import os
import re
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from artemis.agentic.authority import AuthDecision
from artemis.agentic.coder.router import CoderBackend, CoderRouter
from artemis.agentic.coder.workspace import WorkspaceConfig, build_workspace
from artemis.agentic.types import OwnerInbox, PlanStep

if TYPE_CHECKING:
    from openhands.sdk import LocalWorkspace, RemoteWorkspace

_OWNER_YES = {"yes", "y", "approve", "approved", "continue", "ok"}
_MAX_SUMMARY_CHARS = 1_000


class BuildStatus(StrEnum):
    """Bounded coding run outcome."""

    SUCCEEDED = "succeeded"
    DENIED = "denied"
    ERROR = "error"


class BuildTask(BaseModel):
    """Request passed from Artemis planner/spine to the embedded coder."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    instructions: str
    task_class: str = "default"


class BuildResult(BaseModel):
    """Sanitized result surface returned to the Artemis spine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: BuildStatus
    files: tuple[str, ...] = ()
    summary: str = Field(default="", max_length=_MAX_SUMMARY_CHARS)


class ConfirmationDecision(StrEnum):
    """Artemis decision for a pending OpenHands action batch."""

    ALLOW = "allow"
    DENY = "deny"


class AuthorityGateLike(Protocol):
    """Subset of AuthorityGate used by the coder confirmation policy."""

    def authorize(self, step: PlanStep, *, workspace_root: Path) -> AuthDecision: ...


class ConversationLike(Protocol):
    """Small OpenHands conversation surface used by CodingSubsystem."""

    def send_message(self, message: str) -> object: ...

    def run(self) -> object: ...

    def reject_pending_actions(self, reason: str = "User rejected the action") -> None: ...


class ConfigurableConversationLike(ConversationLike, Protocol):
    """OpenHands conversation methods used only during live adapter setup."""

    def set_confirmation_policy(self, policy: object) -> None: ...

    def set_security_analyzer(self, analyzer: object) -> None: ...


class OpenHandsAdapter(Protocol):
    """Fake-able adapter for live OpenHands construction."""

    is_live: bool

    def create_conversation(
        self,
        *,
        backend: CoderBackend,
        workspace: object,
        policy: object,
        security_analyzer: object,
    ) -> ConversationLike: ...


class CoderRouterLike(Protocol):
    """Subset of CoderRouter used by the subsystem."""

    def select(self, task_class: str) -> CoderBackend: ...


class ArtemisConfirmationPolicy:
    """Fail-closed bridge from OpenHands confirmation pauses to Artemis GATE."""

    _authority: AuthorityGateLike
    _inbox: OwnerInbox
    _workspace_root: Path

    def __init__(
        self,
        *,
        authority: AuthorityGateLike,
        inbox: OwnerInbox,
        workspace_root: Path,
    ) -> None:
        self._authority = authority
        self._inbox = inbox
        self._workspace_root = workspace_root

    def should_confirm(self, risk: object = None) -> bool:
        """OpenHands policy hook: every non-trivial action pauses for Artemis."""
        del risk
        return True

    async def decide(self, event: object, *, risk: object = None) -> ConfirmationDecision:
        """Authorize one WAITING_FOR_CONFIRMATION event through Artemis.

        Analyzer output is carried as metadata only; it never short-circuits the
        authority gate.
        """
        step = _step_from_event(event, risk=risk)
        try:
            decision = self._authority.authorize(step, workspace_root=self._workspace_root)
        except Exception:  # noqa: BLE001 - confirmation must fail closed.
            return ConfirmationDecision.DENY

        if decision.auto:
            return ConfirmationDecision.ALLOW

        if decision.pending is None:
            return ConfirmationDecision.DENY

        try:
            answer = await self._inbox.ask(
                f"Authorize {decision.summary}? pending={decision.pending.id}",
                options=("yes", "no"),
            )
        except Exception:  # noqa: BLE001 - inbox failure must fail closed.
            return ConfirmationDecision.DENY

        if answer is None:
            return ConfirmationDecision.DENY
        return (
            ConfirmationDecision.ALLOW
            if answer.strip().lower() in _OWNER_YES
            else ConfirmationDecision.DENY
        )


class ArtemisSecurityAnalyzer:
    """Minimal analyzer seam; OpenHands risk is advisory metadata for GATE."""

    def analyze_pending_actions(self, pending_actions: list[object]) -> list[tuple[object, object]]:
        return [(action, _risk_from_event(action)) for action in pending_actions]


class OpenHandsSDKAdapter:
    """Thin lazy-import adapter around OpenHands V1 SDK objects."""

    is_live = True

    def create_conversation(
        self,
        *,
        backend: CoderBackend,
        workspace: object,
        policy: object,
        security_analyzer: object,
    ) -> ConversationLike:
        os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
        from openhands.sdk import LLM, Agent, Conversation

        llm = LLM(model=backend.model, base_url=backend.base_url)
        agent = Agent(llm=llm)
        typed_workspace = cast(
            "str | Path | LocalWorkspace | RemoteWorkspace",
            workspace,
        )
        conversation = cast(
            ConfigurableConversationLike,
            Conversation(agent, workspace=typed_workspace, visualizer=None),
        )
        conversation.set_confirmation_policy(policy)
        conversation.set_security_analyzer(security_analyzer)
        return conversation


class CodingSubsystem:
    """Run coding tasks through router-selected OpenHands backends."""

    def __init__(
        self,
        *,
        authority: AuthorityGateLike,
        inbox: OwnerInbox,
        workspace_config: WorkspaceConfig,
        router: CoderRouterLike | None = None,
        adapter: OpenHandsAdapter | None = None,
        sandbox_active: Callable[[], bool] | bool = False,
    ) -> None:
        self._authority = authority
        self._inbox = inbox
        self._workspace_config = workspace_config
        self._router = router or CoderRouter()
        self._adapter = adapter or OpenHandsSDKAdapter()
        self._sandbox_active = sandbox_active

    async def run(self, task_spec: BuildTask) -> BuildResult:
        """Run a coding task and return a bounded, sanitized result."""
        if (
            self._adapter.is_live
            and self._workspace_config.kind == "local"
            and not self._is_sandbox_active()
        ):
            raise RuntimeError("refusing live local coder run without active AGENT-rung2 sandbox")

        try:
            backend = self._router.select(task_spec.task_class)
            policy = ArtemisConfirmationPolicy(
                authority=self._authority,
                inbox=self._inbox,
                workspace_root=self._workspace_config.root,
            )
            conversation = self._adapter.create_conversation(
                backend=backend,
                workspace=build_workspace(self._workspace_config),
                policy=policy,
                security_analyzer=ArtemisSecurityAnalyzer(),
            )
            conversation.send_message(task_spec.instructions)
            return await self._drive_conversation(conversation, policy)
        except Exception:  # noqa: BLE001 - SDK details are not forwarded to planner.
            return BuildResult(status=BuildStatus.ERROR, summary="coder failed")

    async def _drive_conversation(
        self,
        conversation: ConversationLike,
        policy: ArtemisConfirmationPolicy,
    ) -> BuildResult:
        last_result: object = None
        for _ in range(20):
            last_result = conversation.run()
            if not _is_waiting_for_confirmation(conversation, last_result):
                return _result_from_conversation(conversation, last_result)

            event = _confirmation_event(conversation, last_result)
            risk = _risk_from_event(event)
            decision = await policy.decide(event, risk=risk)
            if decision is ConfirmationDecision.DENY:
                conversation.reject_pending_actions("Artemis authority denied the action")
                return BuildResult(status=BuildStatus.DENIED, summary="coder action denied")

        return BuildResult(status=BuildStatus.ERROR, summary="coder confirmation limit reached")

    def _is_sandbox_active(self) -> bool:
        if isinstance(self._sandbox_active, bool):
            return self._sandbox_active
        return self._sandbox_active()


def _step_from_event(event: object, *, risk: object) -> PlanStep:
    tool_ref = _string_attr(event, "tool_ref", "tool_name", "name") or type(event).__name__
    description = _string_attr(event, "summary", "description", "message") or tool_ref
    args = _args_from_event(event)
    if risk is not None:
        args["security_risk"] = str(risk)
    return PlanStep(
        id=_string_attr(event, "id", "event_id") or "openhands-confirmation",
        description=description,
        tool_ref=tool_ref,
        args=args,
        verify="OpenHands action completed",
    )


def _args_from_event(event: object) -> dict[str, str | int | float | bool]:
    raw = _attr(event, "args", "arguments", "metadata")
    if not isinstance(raw, dict):
        return {}
    args: dict[str, str | int | float | bool] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str | int | float | bool):
            args[key] = value
    return args


def _risk_from_event(event: object) -> object:
    return _attr(event, "risk", "security_risk")


def _attr(event: object, *names: str) -> object:
    for name in names:
        if hasattr(event, name):
            return getattr(event, name)
    if isinstance(event, dict):
        for name in names:
            value = event.get(name)
            if value is not None:
                return value
    return None


def _string_attr(event: object, *names: str) -> str | None:
    value = _attr(event, *names)
    return value if isinstance(value, str) else None


def _is_waiting_for_confirmation(conversation: ConversationLike, result: object) -> bool:
    values = (
        _attr(result, "status", "execution_status"),
        _attr(_attr(conversation, "state"), "execution_status"),
    )
    return any(str(value).lower().endswith("waiting_for_confirmation") for value in values)


def _confirmation_event(conversation: ConversationLike, result: object) -> object:
    value = _attr(result, "confirmation_event", "event", "pending_action")
    if value is not None:
        return value
    value = _attr(conversation, "confirmation_event", "event", "pending_action")
    if value is not None:
        return value
    pending = _attr(conversation, "pending_actions")
    if isinstance(pending, list) and pending:
        return pending[0]
    return result


def _result_from_conversation(conversation: ConversationLike, result: object) -> BuildResult:
    files = _sanitize_files(_attr(result, "files", "changed_files") or _attr(conversation, "files"))
    summary_source = _attr(result, "summary", "message") or _attr(conversation, "summary")
    return BuildResult(
        status=BuildStatus.SUCCEEDED,
        files=files,
        summary=_sanitize_summary(summary_source),
    )


def _sanitize_files(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        return ()
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str | Path):
            continue
        path = Path(item)
        values.append(path.name if path.is_absolute() else path.as_posix())
    return tuple(values)


def _sanitize_summary(raw: object) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    for line in text.splitlines():
        if "stdout" in line.lower() or "stderr" in line.lower():
            text = text.replace(line, "")
    text = re.sub(r"[A-Za-z]:\\[^\s]+", "[path]", text)
    text = re.sub(r"/(?:[^/\s]+/)+[^/\s]+", "[path]", text)
    return text.strip()[:_MAX_SUMMARY_CHARS]


def openhands_api_summary() -> dict[str, str]:
    """Return a small import-surface summary for tests/diagnostics."""
    os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
    from openhands.sdk import LLM, Agent, Conversation, Tool

    return {
        "LLM": str(inspect.signature(LLM)),
        "Agent": str(inspect.signature(Agent)),
        "Conversation": str(inspect.signature(Conversation)),
        "Tool": Tool.__name__,
    }
