from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from artemis.agentic.authority import AuthDecision, PendingActionRef
from artemis.agentic.coder.router import CoderBackend
from artemis.agentic.coder.subsystem import (
    ArtemisConfirmationPolicy,
    BuildStatus,
    BuildTask,
    CodingSubsystem,
    ConfirmationDecision,
    openhands_api_summary,
)
from artemis.agentic.coder.workspace import WorkspaceConfig, build_workspace
from artemis.agentic.types import PlanStep


@dataclass(frozen=True)
class FakeEvent:
    id: str
    tool_ref: str
    args: dict[str, str | int | float | bool]
    security_risk: str = "LOW"


@dataclass(frozen=True)
class FakeRunResult:
    status: str
    confirmation_event: FakeEvent | None = None
    files: list[str] | None = None
    summary: str = ""


class FakeAuthority:
    def __init__(self, decisions: list[AuthDecision] | None = None, *, fail: bool = False) -> None:
        self.decisions = decisions or [AuthDecision(auto=True, summary="auto")]
        self.fail = fail
        self.calls: list[PlanStep] = []

    def authorize(self, step: PlanStep, *, workspace_root: Path) -> AuthDecision:
        del workspace_root
        self.calls.append(step)
        if self.fail:
            raise RuntimeError("authority exploded C:\\secret\\path")
        if len(self.calls) <= len(self.decisions):
            return self.decisions[len(self.calls) - 1]
        return self.decisions[-1]


class FakeInbox:
    def __init__(self, answers: list[str | None] | None = None, *, fail: bool = False) -> None:
        self.answers = answers or []
        self.fail = fail
        self.calls: list[str] = []

    async def ask(
        self, question: str, *, options: tuple[str, ...] = (), timeout_s: int = 0
    ) -> str | None:
        del options, timeout_s
        self.calls.append(question)
        if self.fail:
            raise RuntimeError("inbox exploded C:\\secret\\path")
        if len(self.calls) <= len(self.answers):
            return self.answers[len(self.calls) - 1]
        return "yes"


class FakeRouter:
    def __init__(self) -> None:
        self.selected: list[str] = []
        self.backend = CoderBackend(
            model="fake-model",
            base_url="https://models.invalid",
            api_key_env="FAKE_KEY",
            tier="cheap",
        )

    def select(self, task_class: str) -> CoderBackend:
        self.selected.append(task_class)
        return self.backend


class FakeConversation:
    def __init__(self, runs: list[FakeRunResult]) -> None:
        self.runs = runs
        self.messages: list[str] = []
        self.rejects: list[str] = []
        self.files = ["C:\\raw\\absolute\\secret.txt"]
        self.summary = "stdout: raw\ncompleted from C:\\raw\\absolute"

    def send_message(self, message: str) -> object:
        self.messages.append(message)
        return None

    def run(self) -> object:
        return self.runs.pop(0)

    def reject_pending_actions(self, reason: str = "User rejected the action") -> None:
        self.rejects.append(reason)


class FakeAdapter:
    is_live = False

    def __init__(self, conversation: FakeConversation) -> None:
        self.conversation = conversation
        self.backends: list[CoderBackend] = []
        self.workspaces: list[object] = []
        self.policies: list[object] = []

    def create_conversation(
        self,
        *,
        backend: CoderBackend,
        workspace: object,
        policy: object,
        security_analyzer: object,
    ) -> FakeConversation:
        del security_analyzer
        self.backends.append(backend)
        self.workspaces.append(workspace)
        self.policies.append(policy)
        return self.conversation


@pytest.mark.asyncio
async def test_every_waiting_confirmation_routes_through_authority(tmp_path: Path) -> None:
    events = [
        FakeEvent("e1", "shell.run", {"command": "one"}),
        FakeEvent("e2", "fs.write", {"target": "two.txt"}),
    ]
    conversation = FakeConversation(
        [
            FakeRunResult("waiting_for_confirmation", events[0]),
            FakeRunResult("waiting_for_confirmation", events[1]),
            FakeRunResult("finished", files=["changed.py"], summary="done"),
        ]
    )
    authority = FakeAuthority()

    result = await _subsystem(tmp_path, authority, FakeInbox(), conversation).run(
        BuildTask(id="t1", instructions="build", task_class="feature")
    )

    assert result.status is BuildStatus.SUCCEEDED
    assert [call.tool_ref for call in authority.calls] == ["shell.run", "fs.write"]
    assert conversation.rejects == []


@pytest.mark.asyncio
async def test_low_risk_boundary_still_calls_authorize(tmp_path: Path) -> None:
    event = FakeEvent("e1", "fs.write", {"target": "../outside.txt"}, security_risk="LOW")
    authority = FakeAuthority()
    policy = ArtemisConfirmationPolicy(
        authority=authority,
        inbox=FakeInbox(),
        workspace_root=tmp_path,
    )

    decision = await policy.decide(event, risk="LOW")

    assert decision is ConfirmationDecision.ALLOW
    assert len(authority.calls) == 1
    assert authority.calls[0].args["security_risk"] == "LOW"


@pytest.mark.asyncio
async def test_policy_fail_closed_on_authority_error_and_inbox_timeout(tmp_path: Path) -> None:
    event = FakeEvent("e1", "shell.run", {"command": "danger"})
    authority_error = ArtemisConfirmationPolicy(
        authority=FakeAuthority(fail=True),
        inbox=FakeInbox(),
        workspace_root=tmp_path,
    )
    pending = ArtemisConfirmationPolicy(
        authority=FakeAuthority(
            [AuthDecision(auto=False, pending=PendingActionRef("p1"), summary="boundary")]
        ),
        inbox=FakeInbox([None]),
        workspace_root=tmp_path,
    )

    assert await authority_error.decide(event, risk="HIGH") is ConfirmationDecision.DENY
    assert await pending.decide(event, risk="HIGH") is ConfirmationDecision.DENY


@pytest.mark.asyncio
async def test_denied_confirmation_rejects_and_does_not_proceed(tmp_path: Path) -> None:
    event = FakeEvent("e1", "shell.run", {"command": "danger"})
    conversation = FakeConversation([FakeRunResult("waiting_for_confirmation", event)])
    authority = FakeAuthority(
        [AuthDecision(auto=False, pending=PendingActionRef("p1"), summary="boundary")]
    )

    result = await _subsystem(
        tmp_path,
        authority,
        FakeInbox([None]),
        conversation,
    ).run(BuildTask(id="t1", instructions="build"))

    assert result.status is BuildStatus.DENIED
    assert conversation.rejects == ["Artemis authority denied the action"]
    assert conversation.runs == []


@pytest.mark.asyncio
async def test_live_local_run_without_sandbox_raises(tmp_path: Path) -> None:
    class LiveAdapter(FakeAdapter):
        is_live = True

    subsystem = CodingSubsystem(
        authority=FakeAuthority(),
        inbox=FakeInbox(),
        workspace_config=WorkspaceConfig(kind="local", root=tmp_path),
        router=FakeRouter(),
        adapter=LiveAdapter(FakeConversation([])),
    )

    with pytest.raises(RuntimeError, match="AGENT-rung2 sandbox"):
        await subsystem.run(BuildTask(id="t1", instructions="build"))


@pytest.mark.asyncio
async def test_build_result_sanitized_router_used_and_fake_run_no_live_call(tmp_path: Path) -> None:
    conversation = FakeConversation(
        [
            FakeRunResult(
                "finished",
                files=[str(tmp_path / "secret" / "result.py")],
                summary="stdout: raw logs\nall good from C:\\private\\repo",
            )
        ]
    )
    router = FakeRouter()
    adapter = FakeAdapter(conversation)

    result = await _subsystem(
        tmp_path,
        FakeAuthority(),
        FakeInbox(),
        conversation,
        router=router,
        adapter=adapter,
    ).run(BuildTask(id="t1", instructions="build", task_class="bugfix"))

    assert result.status is BuildStatus.SUCCEEDED
    assert result.files == ("result.py",)
    assert "stdout" not in result.summary.lower()
    assert "raw logs" not in result.summary
    assert str(tmp_path) not in result.summary
    assert "C:\\private" not in result.summary
    assert router.selected == ["bugfix"]
    assert adapter.backends == [router.backend]
    assert conversation.messages == ["build"]


def test_build_workspace_selects_by_config(tmp_path: Path) -> None:
    local = build_workspace(WorkspaceConfig(kind="local", root=tmp_path))
    docker = build_workspace(
        WorkspaceConfig(kind="docker", root=Path("/workspace"), connection="http://127.0.0.1")
    )
    remote = build_workspace(
        WorkspaceConfig(kind="remote", root=Path("/workspace"), connection="http://127.0.0.1")
    )

    assert type(local).__name__ == "LocalWorkspace"
    assert type(docker).__name__ == "RemoteWorkspace"
    assert type(remote).__name__ == "RemoteWorkspace"


def test_openhands_import_surface_matches_installed_sdk() -> None:
    summary = openhands_api_summary()

    assert "model" in summary["LLM"]
    assert "llm" in summary["Agent"]
    assert "workspace" in summary["Conversation"]
    assert summary["Tool"] == "Tool"


def _subsystem(
    tmp_path: Path,
    authority: FakeAuthority,
    inbox: FakeInbox,
    conversation: FakeConversation,
    *,
    router: FakeRouter | None = None,
    adapter: FakeAdapter | None = None,
) -> CodingSubsystem:
    return CodingSubsystem(
        authority=authority,
        inbox=inbox,
        workspace_config=WorkspaceConfig(kind="remote", root=tmp_path, connection="http://fake"),
        router=router or FakeRouter(),
        adapter=adapter or FakeAdapter(conversation),
    )
