"""OpenHands workspace selection seam for the embedded coder.

The Artemis security model keeps platform divergence here: Windows development
uses OpenHands' local workspace and relies on the AGENT-rung2 sandbox wrapper,
while Mac/prod configurations can swap to a remote workspace.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WorkspaceKind = Literal["local", "docker", "remote"]


def _default_workspace_kind() -> WorkspaceKind:
    return "local" if sys.platform == "win32" else "docker"


class WorkspaceConfig(BaseModel):
    """Config-only selector for the OpenHands workspace implementation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: WorkspaceKind = Field(default_factory=_default_workspace_kind)
    root: Path = Path("workspace/project")
    connection: str | None = None


def build_workspace(cfg: WorkspaceConfig) -> object:
    """Build the matching OpenHands workspace object.

    OpenHands is imported lazily so test paths that inject fake conversations do
    not pay the SDK import cost or display its banner.
    """
    os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
    if cfg.kind == "local":
        from openhands.sdk import LocalWorkspace

        return LocalWorkspace(working_dir=cfg.root)

    from openhands.sdk import RemoteWorkspace

    if cfg.connection is None:
        raise ValueError(f"{cfg.kind} workspace requires connection")
    return RemoteWorkspace(working_dir=str(cfg.root), host=cfg.connection)
