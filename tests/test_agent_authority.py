from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from artemis import paths
from artemis.agentic.authority import AuthDecision, AuthorityGate, PendingActionRef
from artemis.agentic.types import Crossing, PlanStep
from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.staging.model import ActionStatus, PendingAction


class FakePendingStore:
    def __init__(self) -> None:
        self.actions: dict[str, PendingAction] = {}

    def get(self, action_id: str) -> PendingAction:
        return self.actions[action_id]


class FakeStaging:
    def __init__(self, *, fail: bool = False) -> None:
        self.store = FakePendingStore()
        self.fail = fail
        self.calls: list[tuple[str, str, dict[str, object], str, timedelta | None]] = []

    def stage(
        self,
        module: str,
        tool: str,
        args: dict[str, object],
        summary: str,
        *,
        ttl: timedelta | None = None,
    ) -> PendingAction:
        if self.fail:
            raise RuntimeError("staging backend exploded with secret path C:\\private")
        self.calls.append((module, tool, args, summary, ttl))
        now = datetime.now(UTC)
        action = PendingAction(
            id=f"action-{len(self.calls)}",
            module=module,
            tool=tool,
            args=args,
            summary=summary,
            action_class="takes-action",
            status=ActionStatus.PENDING,
            created_at=now,
            expires_at=now + (ttl or timedelta(hours=1)),
        )
        self.store.actions[action.id] = action
        return action

    def approve(self, action_id: str) -> None:
        action = self.store.get(action_id)
        self.store.actions[action_id] = action.model_copy(update={"status": ActionStatus.APPROVED})

    def forge_approved_signature(self, action_id: str, signature: str) -> None:
        action = self.store.get(action_id)
        args = dict(action.args)
        args["__authority_signature"] = signature
        self.store.actions[action_id] = action.model_copy(
            update={"status": ActionStatus.APPROVED, "args": args}
        )


def test_in_sandbox_authorizes_auto_without_staging(tmp_path: Path) -> None:
    staging = FakeStaging()
    gate = _gate(tmp_path, staging)
    workspace = tmp_path / "workspace"
    target = workspace / "notes.txt"
    target.parent.mkdir()
    target.write_text("draft")
    step = _step({"target": "notes.txt", "disposable": True})

    decision = gate.authorize(step, workspace_root=workspace)

    assert decision == AuthDecision(auto=True, pending=None, summary="in_sandbox: fs.write")
    assert staging.calls == []


def test_novel_boundary_stages_and_exposes_only_opaque_ref(tmp_path: Path) -> None:
    staging = FakeStaging()
    gate = _gate(tmp_path, staging)
    step = _step(
        {
            "host": "Example.COM",
            "port": 443,
            "protocol": "HTTPS",
            "disposable": True,
        },
        tool_ref="net.fetch",
    )

    decision = gate.authorize(step, workspace_root=tmp_path / "workspace")

    assert decision.auto is False
    assert decision.pending == PendingActionRef("action-1")
    assert decision.summary == "boundary: net.fetch"
    assert len(staging.calls) == 1
    module, tool, args, summary, ttl = staging.calls[0]
    assert module == "net"
    assert tool == "net.fetch"
    assert summary == "boundary: net.fetch"
    assert ttl == timedelta(hours=24)
    assert args["__authority_crossing"] == Crossing.BOUNDARY.value
    visible = decision.__dict__
    assert set(visible) == {"auto", "pending", "summary"}
    assert str(tmp_path) not in str(visible)
    assert "signature" not in str(visible)


def test_graduation_makes_same_signature_auto_and_changed_target_reasks(tmp_path: Path) -> None:
    staging = FakeStaging()
    gate = _gate(tmp_path, staging)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    step = _step({"target": str(outside), "disposable": True})

    first = gate.authorize(step, workspace_root=workspace)
    assert first.auto is False
    assert first.pending is not None
    staging.approve(first.pending.id)
    assert gate.graduate(first.pending.id) is True

    same = gate.authorize(step, workspace_root=workspace)
    assert same.auto is True
    assert len(staging.calls) == 1

    changed = tmp_path / "other.txt"
    changed.write_text("other")
    changed_decision = gate.authorize(
        _step({"target": str(changed), "disposable": True}),
        workspace_root=workspace,
    )
    assert changed_decision.auto is False
    assert changed_decision.pending == PendingActionRef("action-2")
    assert len(staging.calls) == 2


def test_path_escape_via_parent_and_symlink_classifies_boundary(tmp_path: Path) -> None:
    gate = _gate(tmp_path, FakeStaging())
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = outside / "secret.txt"
    escaped.write_text("secret")

    # The `..` parent-escape fail-closed BLOCK must hold on every host, including
    # the Windows dev box where symlink creation needs privilege — assert it
    # before the (skippable) symlink setup so it is never skipped.
    parent_escape = _step({"target": "../outside/secret.txt", "disposable": True})
    assert gate.classify(parent_escape, workspace_root=workspace) is Crossing.BOUNDARY

    link = workspace / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this host")

    symlink_escape = _step({"target": "link/secret.txt", "disposable": True})
    assert gate.classify(symlink_escape, workspace_root=workspace) is Crossing.BOUNDARY


def test_resolution_error_and_unknown_fail_closed(tmp_path: Path) -> None:
    gate = _gate(tmp_path, FakeStaging())
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    missing = _step({"target": "missing.txt", "disposable": True})
    unknown = _step({"command": "tool --flag"})

    assert gate.classify(missing, workspace_root=workspace) is Crossing.BOUNDARY
    assert gate.classify(unknown, workspace_root=workspace) is Crossing.BOUNDARY


def test_stage_error_propagates_and_never_auto_runs(tmp_path: Path) -> None:
    gate = _gate(tmp_path, FakeStaging(fail=True))
    step = _step({"host": "example.com", "port": 443, "protocol": "https", "disposable": True})

    with pytest.raises(RuntimeError, match="staging backend exploded"):
        gate.authorize(step, workspace_root=tmp_path / "workspace")


def test_graduate_refuses_unapproved_or_forged_actions(tmp_path: Path) -> None:
    staging = FakeStaging()
    gate = _gate(tmp_path, staging)
    step = _step({"host": "example.com", "port": 443, "protocol": "https", "disposable": True})

    decision = gate.authorize(step, workspace_root=tmp_path / "workspace")
    assert decision.pending is not None
    assert gate.graduate(decision.pending.id) is False

    staging.forge_approved_signature(decision.pending.id, "0" * 64)
    assert gate.graduate(decision.pending.id) is False
    assert gate.authorize(step, workspace_root=tmp_path / "workspace").auto is False


def test_allowlist_persists_under_owner_private_and_uses_bound_values(tmp_path: Path) -> None:
    staging = FakeStaging()
    settings = Settings(data_root=tmp_path)
    key_provider = FakeKeyProvider({OWNER_PRIVATE: b"1" * 32}, owner_unlocked=True)
    gate = AuthorityGate(settings, key_provider, staging)
    step = _step(
        {
            "host": "example.com'); DROP TABLE agent_allowlist; --",
            "port": 443,
            "protocol": "https",
            "disposable": True,
        },
        tool_ref="net.fetch",
    )

    decision = gate.authorize(step, workspace_root=tmp_path / "workspace")
    assert decision.pending is not None
    staging.approve(decision.pending.id)
    assert gate.graduate(decision.pending.id) is True

    expected_path = paths.scope_dir(settings, OWNER_PRIVATE) / "agentic" / "agent_allowlist.db"
    assert expected_path.exists()
    assert expected_path.is_relative_to(paths.scope_dir(settings, OWNER_PRIVATE))

    reconstructed = AuthorityGate(settings, key_provider, staging)
    assert reconstructed.authorize(step, workspace_root=tmp_path / "workspace").auto is True


def test_signature_canonicalisation_is_specific(tmp_path: Path) -> None:
    gate = _gate(tmp_path, FakeStaging())
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = workspace / "script.py"
    script.write_text("print('ok')")
    file_target = workspace / "file.txt"
    file_target.write_text("file")

    command_a = gate.signature(
        "shell.run",
        {"argv": f"{script} --count 1", "env_MODE": "prod", "disposable": True},
        Crossing.BOUNDARY,
        workspace_root=workspace,
    )
    command_b = gate.signature(
        "shell.run",
        {"argv": f"{script} --count 2", "env_MODE": "prod", "disposable": True},
        Crossing.BOUNDARY,
        workspace_root=workspace,
    )
    file_sig = gate.signature(
        "shell.run",
        {"target": str(file_target), "disposable": True},
        Crossing.BOUNDARY,
        workspace_root=workspace,
    )
    network_sig = gate.signature(
        "shell.run",
        {"host": "example.com", "port": 443, "protocol": "https", "disposable": True},
        Crossing.BOUNDARY,
        workspace_root=workspace,
    )
    sandbox_sig = gate.signature(
        "shell.run",
        {"host": "example.com", "port": 443, "protocol": "https", "disposable": True},
        Crossing.IN_SANDBOX,
        workspace_root=workspace,
    )

    assert command_a != command_b
    assert command_a != file_sig
    assert network_sig != sandbox_sig


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)


def _gate(tmp_path: Path, staging: FakeStaging) -> AuthorityGate:
    key_provider = FakeKeyProvider({OWNER_PRIVATE: b"1" * 32}, owner_unlocked=True)
    return AuthorityGate(_settings(tmp_path), key_provider, staging)


def _step(
    args: dict[str, str | int | float | bool],
    *,
    tool_ref: str = "fs.write",
) -> PlanStep:
    return PlanStep(
        id="step-1",
        description="Do the thing",
        tool_ref=tool_ref,
        args=args,
        verify="Verify the thing",
    )
