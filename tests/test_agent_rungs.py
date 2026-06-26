"""Tests for Rung 0 host introspection and Rung 1 file operations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from artemis.agentic.authority import AuthorityGate
from artemis.agentic.rungs.fileops import (
    MoveArgs,
    PathArgs,
    WriteTextArgs,
    move,
    register_rung01,
    resolve_within,
    trash,
    write_text,
)
from artemis.agentic.rungs.introspect import EnvGetArgs, PathReadArgs, env_get, read_text
from artemis.agentic.types import Crossing, PlanStep
from artemis.ports.types import Vector
from artemis.registry import ToolRegistry


class FakeEmbedder:
    """Minimal embedder; registration is lazy, but ToolRegistry requires one."""

    @property
    def dimension(self) -> int:
        return 2

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0] for _text in texts]

    async def embed_query(self, query: str) -> Vector:
        return [1.0, 0.0]


@pytest.mark.asyncio
async def test_env_get_allowlist_and_secret_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "allowed-path")
    monkeypatch.setenv("API_KEY", "secret")

    assert (await env_get(EnvGetArgs(name="PATH"))).text == "allowed-path"
    assert (await env_get(EnvGetArgs(name="API_KEY"))).text is None
    assert (await env_get(EnvGetArgs(name="NOT_ALLOWLISTED"))).text is None
    assert (await env_get(EnvGetArgs(name="AUTH"))).text is None


@pytest.mark.asyncio
async def test_read_text_caps_large_files(tmp_path: Path) -> None:
    target = tmp_path / "large.txt"
    target.write_bytes(b"a" * 65_537)

    result = await read_text(PathReadArgs(path=str(target)))

    assert result.text is not None
    assert result.text.startswith("a" * 65_536)
    assert result.text.endswith("[truncated: 65537 bytes total]")


def test_resolve_within_rejects_traversal_and_leaks_no_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    candidate = workspace / "a" / ".." / ".." / outside.name

    with pytest.raises(PermissionError) as exc_info:
        resolve_within(workspace, candidate)

    assert str(exc_info.value) == "path outside workspace"
    assert str(outside) not in str(exc_info.value)
    assert str(workspace) not in str(exc_info.value)


def test_resolve_within_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(PermissionError, match="^path outside workspace$"):
        resolve_within(workspace, link)


@pytest.mark.asyncio
async def test_file_ops_are_confined_and_trash_moves(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    write_result = await write_text(
        WriteTextArgs(path="nested/file.txt", content="hello", disposable=True),
        workspace_root=workspace,
    )
    written = Path(write_result.path)
    assert written.read_text(encoding="utf-8") == "hello"

    trash_result = await trash(
        PathArgs(path=str(written), disposable=True), workspace_root=workspace
    )
    trashed = Path(trash_result.path)

    assert not written.exists()
    assert trashed.exists()
    assert trashed.is_relative_to(workspace / ".agent_trash")
    assert trashed.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_move_validates_both_endpoints(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    source = workspace / "source.txt"
    source.write_text("data", encoding="utf-8")

    with pytest.raises(PermissionError, match="^path outside workspace$"):
        await move(
            MoveArgs(src=str(source), dst=str(outside_dir / "dest.txt"), disposable=True),
            workspace_root=workspace,
        )

    assert source.exists()


def test_register_rung01_registers_expected_tools(tmp_path: Path) -> None:
    registry = ToolRegistry(FakeEmbedder())

    register_rung01(registry, workspace_root=tmp_path)

    for fq_name in (
        "host.cwd",
        "host.os_info",
        "host.env_get",
        "host.read_text",
        "host.list_dir",
        "fs.write_text",
        "fs.mkdir",
        "fs.trash",
        "fs.move",
    ):
        assert registry.get_tool(fq_name).callable_ref is not None


def test_authority_classifies_rung01_blast_radius(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside_file = workspace / "inside.txt"
    inside_file.write_text("inside", encoding="utf-8")
    inside_dir = workspace / "dir"
    inside_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    gate = AuthorityGate.__new__(AuthorityGate)

    auto_steps = (
        PlanStep(
            id="cwd", description="cwd", tool_ref="host.cwd", args={"disposable": True}, verify=""
        ),
        PlanStep(
            id="os",
            description="os",
            tool_ref="host.os_info",
            args={"disposable": True},
            verify="",
        ),
        PlanStep(
            id="env",
            description="env",
            tool_ref="host.env_get",
            args={"name": "PATH", "disposable": True},
            verify="",
        ),
        PlanStep(
            id="read",
            description="read",
            tool_ref="host.read_text",
            args={"path": str(inside_file), "disposable": True},
            verify="",
        ),
        PlanStep(
            id="list",
            description="list",
            tool_ref="host.list_dir",
            args={"path": str(inside_dir), "disposable": True},
            verify="",
        ),
        PlanStep(
            id="write",
            description="write",
            tool_ref="fs.write_text",
            args={"path": str(inside_file), "content": "x", "disposable": True},
            verify="",
        ),
        PlanStep(
            id="mkdir",
            description="mkdir",
            tool_ref="fs.mkdir",
            args={"path": str(inside_dir), "disposable": True},
            verify="",
        ),
        PlanStep(
            id="trash",
            description="trash",
            tool_ref="fs.trash",
            args={"path": str(inside_file), "disposable": True},
            verify="",
        ),
        PlanStep(
            id="move",
            description="move",
            tool_ref="fs.move",
            args={
                "path": str(inside_file),
                "src": "inside.txt",
                "dst": "inside2.txt",
                "disposable": True,
            },
            verify="",
        ),
    )

    for step in auto_steps:
        assert gate.classify(step, workspace_root=workspace) is Crossing.IN_SANDBOX

    for tool_ref in ("host.read_text", "host.list_dir"):
        step = PlanStep(
            id=tool_ref,
            description=tool_ref,
            tool_ref=tool_ref,
            args={"path": str(outside), "disposable": True},
            verify="",
        )
        assert gate.classify(step, workspace_root=workspace) is Crossing.BOUNDARY
