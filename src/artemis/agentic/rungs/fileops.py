"""Rung 1 reversible, workspace-confined file operation tools."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from artemis.agentic.rungs.introspect import host_manifest
from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec
from artemis.registry import ToolRegistry


class WriteTextArgs(BaseModel):
    """Arguments for workspace-confined text writes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    content: str
    disposable: bool = False


class PathArgs(BaseModel):
    """Single workspace path argument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    disposable: bool = False


class MoveArgs(BaseModel):
    """Workspace-confined move endpoints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    src: str
    dst: str
    path: str | None = None
    disposable: bool = False


class FileOpResult(BaseModel):
    """Result for a reversible file operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    path: str


def resolve_within(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and require it to remain under ``root``."""
    try:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise PermissionError("path outside workspace") from exc
    if not resolved_candidate.is_relative_to(resolved_root):
        raise PermissionError("path outside workspace")
    return resolved_candidate


async def write_text(args: WriteTextArgs, *, workspace_root: Path) -> FileOpResult:
    """Write text only inside the resolved workspace root."""
    target = resolve_within(workspace_root, _candidate(workspace_root, args.path))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.content, encoding="utf-8")
    return FileOpResult(ok=True, path=str(target))


async def mkdir(args: PathArgs, *, workspace_root: Path) -> FileOpResult:
    """Create a directory only inside the resolved workspace root."""
    target = resolve_within(workspace_root, _candidate(workspace_root, args.path))
    target.mkdir(parents=True, exist_ok=True)
    return FileOpResult(ok=True, path=str(target))


async def trash(args: PathArgs, *, workspace_root: Path) -> FileOpResult:
    """Move a workspace path into workspace-local trash instead of deleting it."""
    target = resolve_within(workspace_root, _candidate(workspace_root, args.path))
    trash_dir = resolve_within(workspace_root, workspace_root / ".agent_trash")
    trash_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = resolve_within(workspace_root, trash_dir / f"{stamp}-{target.name}")
    shutil.move(str(target), str(destination))
    return FileOpResult(ok=True, path=str(destination))


async def move(args: MoveArgs, *, workspace_root: Path) -> FileOpResult:
    """Move a workspace path after validating both source and destination."""
    source = resolve_within(workspace_root, _candidate(workspace_root, args.src))
    destination = resolve_within(workspace_root, _candidate(workspace_root, args.dst))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return FileOpResult(ok=True, path=str(destination))


def fileops_manifest(*, workspace_root: Path) -> ModuleManifest:
    """Build the Rung 1 file operation manifest with workspace-bound callables."""
    return ModuleManifest(
        name="fs",
        version="0.1.0",
        description="Reversible workspace-confined file operations.",
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        tools=[
            ToolSpec(
                name="write_text",
                description="Write UTF-8 text inside the workspace.",
                args_schema=WriteTextArgs,
                return_schema=FileOpResult,
                callable_ref=partial(write_text, workspace_root=workspace_root),
                action_risk=ActionRisk.WRITE,
            ),
            ToolSpec(
                name="mkdir",
                description="Create a directory inside the workspace.",
                args_schema=PathArgs,
                return_schema=FileOpResult,
                callable_ref=partial(mkdir, workspace_root=workspace_root),
                action_risk=ActionRisk.WRITE,
            ),
            ToolSpec(
                name="trash",
                description="Move a workspace path into workspace-local trash.",
                args_schema=PathArgs,
                return_schema=FileOpResult,
                callable_ref=partial(trash, workspace_root=workspace_root),
                action_risk=ActionRisk.WRITE,
            ),
            ToolSpec(
                name="move",
                description="Move a path within the workspace.",
                args_schema=MoveArgs,
                return_schema=FileOpResult,
                callable_ref=partial(move, workspace_root=workspace_root),
                action_risk=ActionRisk.WRITE,
            ),
        ],
    )


def register_rung01(registry: ToolRegistry, *, workspace_root: Path) -> None:
    """Register Rung 0 and Rung 1 tools in the existing ToolRegistry."""
    registry.register(host_manifest())
    registry.register(fileops_manifest(workspace_root=workspace_root))


def _candidate(workspace_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return workspace_root / path
