"""Rung 0 read-only host introspection tools."""

from __future__ import annotations

import os
import platform
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec

_READ_LIMIT_BYTES = 65_536
_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USERPROFILE",
        "USERNAME",
        "COMPUTERNAME",
        "TEMP",
        "TMP",
        "APPDATA",
        "LOCALAPPDATA",
        "PWD",
        "SHELL",
        "LANG",
        "LC_ALL",
        "TERM",
        "OS",
        "PROCESSOR_ARCHITECTURE",
    }
)
_SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH")


class NoArgs(BaseModel):
    """Arguments for host reads that need no caller input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposable: bool = False


class EnvGetArgs(BaseModel):
    """Environment variable lookup constrained to a fixed non-secret allowlist."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    disposable: bool = False


class PathReadArgs(BaseModel):
    """Path argument for read-only host inspection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    disposable: bool = False


class TextResult(BaseModel):
    """Single text result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None


class OsInfoResult(BaseModel):
    """Basic operating-system and Python runtime details."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str
    release: str
    version: str
    machine: str
    python_version: str


class ListDirResult(BaseModel):
    """Directory entries sorted by name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[str, ...]


async def cwd(args: NoArgs) -> TextResult:
    """Return the current process working directory without mutating host state."""
    del args
    return TextResult(text=str(Path.cwd()))


async def os_info(args: NoArgs) -> OsInfoResult:
    """Return read-only operating-system metadata."""
    del args
    return OsInfoResult(
        system=platform.system(),
        release=platform.release(),
        version=platform.version(),
        machine=platform.machine(),
        python_version=platform.python_version(),
    )


async def env_get(args: EnvGetArgs) -> TextResult:
    """Return an allowlisted non-secret environment value or the None sentinel."""
    name = args.name.strip()
    upper_name = name.upper()
    if upper_name not in _ENV_ALLOWLIST or any(marker in upper_name for marker in _SECRET_MARKERS):
        return TextResult(text=None)
    return TextResult(text=os.environ.get(upper_name))


async def read_text(args: PathReadArgs) -> TextResult:
    """Read bounded UTF-8-ish text from a host path."""
    path = Path(args.path)
    size = path.stat().st_size
    with path.open("rb") as handle:
        data = handle.read(_READ_LIMIT_BYTES)
    text = data.decode("utf-8", errors="replace")
    if size > _READ_LIMIT_BYTES:
        text = f"{text}[truncated: {size} bytes total]"
    return TextResult(text=text)


async def list_dir(args: PathReadArgs) -> ListDirResult:
    """List a directory without reading file contents."""
    entries = tuple(sorted(child.name for child in Path(args.path).iterdir()))
    return ListDirResult(entries=entries)


def host_manifest() -> ModuleManifest:
    """Build the Rung 0 host-introspection manifest."""
    return ModuleManifest(
        name="host",
        version="0.1.0",
        description="Read-only host introspection tools.",
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        tools=[
            ToolSpec(
                name="cwd",
                description="Return the current process working directory.",
                args_schema=NoArgs,
                return_schema=TextResult,
                callable_ref=cwd,
                action_risk=ActionRisk.NO_DATA,
            ),
            ToolSpec(
                name="os_info",
                description="Return operating-system and Python runtime metadata.",
                args_schema=NoArgs,
                return_schema=OsInfoResult,
                callable_ref=os_info,
                action_risk=ActionRisk.NO_DATA,
            ),
            ToolSpec(
                name="env_get",
                description="Return one allowlisted non-secret environment variable.",
                args_schema=EnvGetArgs,
                return_schema=TextResult,
                callable_ref=env_get,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="read_text",
                description="Read bounded text from a host path.",
                args_schema=PathReadArgs,
                return_schema=TextResult,
                callable_ref=read_text,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="list_dir",
                description="List the entries in a host directory.",
                args_schema=PathReadArgs,
                return_schema=ListDirResult,
                callable_ref=list_dir,
                action_risk=ActionRisk.READ,
            ),
        ],
    )
