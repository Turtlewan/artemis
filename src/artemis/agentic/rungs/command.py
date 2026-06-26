"""Rung 2 sandboxed command execution tool."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from artemis.agentic.authority import AuthDecision
from artemis.agentic.sandbox import CommandResult, Sandbox
from artemis.agentic.types import PlanStep
from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec
from artemis.registry import ToolRegistry


class AuthorityLike(Protocol):
    """Authority subset required by the command tool."""

    def authorize(self, step: PlanStep, *, workspace_root: Path) -> AuthDecision: ...


class CommandRunArgs(BaseModel):
    """Arguments for ``proc.run``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    argv: tuple[str, ...]
    disposable: bool = True
    timeout_s: int = 30
    allow_network: frozenset[str] | None = None

    @field_validator("argv")
    @classmethod
    def _argv_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("argv must not be empty")
        return value


async def run_command(
    args: CommandRunArgs,
    *,
    sandbox: Sandbox,
    authority: AuthorityLike,
    workspace_root: Path,
) -> CommandResult:
    """Authorize and execute an argv-only command inside the injected sandbox."""
    step_args: dict[str, str | int | float | bool] = {
        "argv": json.dumps(list(args.argv)),
        "disposable": args.disposable,
        "timeout_s": args.timeout_s,
    }
    if args.allow_network:
        step_args["network"] = True
        step_args["host"] = ",".join(sorted(args.allow_network))
    step = PlanStep(
        id="proc.run",
        description="Run argv-only command in sandbox",
        tool_ref="proc.run",
        args=step_args,
        verify="exit_code:0",
    )
    try:
        decision = authority.authorize(step, workspace_root=workspace_root)
    except Exception as exc:  # noqa: BLE001 - fail closed; never run after gate failure.
        return CommandResult(
            exit_code=2,
            stdout="",
            stderr=f"authority failed closed: {type(exc).__name__}",
        )
    if not decision.auto:
        pending = "" if decision.pending is None else f" pending={decision.pending.id}"
        return CommandResult(
            exit_code=202,
            stdout="",
            stderr=f"needs-approval: {decision.summary}{pending}",
        )
    return await sandbox.run(
        args.argv,
        workspace_root=workspace_root,
        allow_network=args.allow_network,
        timeout_s=args.timeout_s,
    )


def command_manifest(
    *,
    sandbox: Sandbox,
    authority: AuthorityLike,
    workspace_root: Path,
) -> ModuleManifest:
    """Build the Rung 2 command manifest with injected confinement seams."""
    return ModuleManifest(
        name="proc",
        version="0.1.0",
        description="Sandboxed argv-only command execution.",
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        tools=[
            ToolSpec(
                name="run",
                description="Run an argv-only command through AuthorityGate and Sandbox.",
                args_schema=CommandRunArgs,
                return_schema=CommandResult,
                callable_ref=partial(
                    run_command,
                    sandbox=sandbox,
                    authority=authority,
                    workspace_root=workspace_root,
                ),
                action_risk=ActionRisk.WRITE,
            )
        ],
    )


def register_rung2(
    registry: ToolRegistry,
    *,
    sandbox: Sandbox,
    authority: AuthorityLike,
    workspace_root: Path,
) -> None:
    """Register the Rung 2 command tool in the existing ToolRegistry."""
    registry.register(
        command_manifest(
            sandbox=sandbox,
            authority=authority,
            workspace_root=workspace_root,
        )
    )
