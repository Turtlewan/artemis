"""Authority gate for agentic blast-radius decisions.

The gate does not execute actions. It classifies a planned step, stages boundary
crossings through GATE, and records only owner-approved exact signatures in an
owner-private SQLCipher allowlist.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from artemis import paths
from artemis.agentic.types import Crossing, PlanStep
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.staging.model import ActionStatus, PendingAction

_DEFAULT_STAGE_TTL = timedelta(hours=24)
_AUTH_META_ARGS = {
    "__authority_crossing",
    "__authority_signature",
    "__authority_tool_ref",
    "__authority_workspace_root",
}


class _PendingActionStore(Protocol):
    def get(self, action_id: str) -> PendingAction: ...


class _StagingService(Protocol):
    @property
    def store(self) -> _PendingActionStore: ...

    def stage(
        self,
        module: str,
        tool: str,
        args: dict[str, object],
        summary: str,
        *,
        ttl: timedelta | None = None,
    ) -> PendingAction: ...


@dataclass(frozen=True)
class PendingActionRef:
    """Opaque reference to an owner-private staged action."""

    id: str


@dataclass(frozen=True)
class AuthDecision:
    """Caller-visible authorization result.

    Only ``auto``, an opaque pending-action reference, and a short redacted
    summary are exposed. Resolved paths, signatures, and exception details stay
    inside the authority/staging stores.
    """

    auto: bool
    pending: PendingActionRef | None = None
    summary: str = ""


class AuthorityGate:
    """Classify action blast radius and graduate owner-approved signatures.

    Classification is fail-closed: in-sandbox is allowed only for steps that
    declare no network, resolve every write target inside the resolved workspace
    root, and mark the action disposable. Unknown or unresolvable actions are
    boundary crossings.

    Signature canonicalisation is stable and specific: command/script actions
    hash the normalized absolute argv tuple plus behavior-affecting env values;
    file operations hash the resolved absolute target path; network actions hash
    host, port, and protocol. Every signature includes ``crossing.value``.
    """

    def __init__(
        self,
        settings: Settings,
        key_provider: KeyProvider,
        staging: _StagingService,
        *,
        stage_ttl: timedelta = _DEFAULT_STAGE_TTL,
    ) -> None:
        self._settings = settings
        self._key_provider = key_provider
        self._staging = staging
        self._stage_ttl = stage_ttl

    def classify(self, step: PlanStep, *, workspace_root: Path) -> Crossing:
        """Return ``IN_SANDBOX`` only for disposable, workspace-contained steps."""
        if not _is_disposable(step):
            return Crossing.BOUNDARY
        if _declares_network(step):
            return Crossing.BOUNDARY

        try:
            resolved_workspace_root = workspace_root.resolve()
            for target in _write_targets(step):
                resolved_target = _path_from_arg(target, resolved_workspace_root).resolve(
                    strict=True
                )
                if not resolved_target.is_relative_to(resolved_workspace_root):
                    return Crossing.BOUNDARY
        except (OSError, RuntimeError, ValueError):
            return Crossing.BOUNDARY

        return Crossing.IN_SANDBOX

    def authorize(self, step: PlanStep, *, workspace_root: Path) -> AuthDecision:
        """Authorize ``step``, staging ungraduated boundary crossings via GATE."""
        crossing = self.classify(step, workspace_root=workspace_root)
        if crossing is Crossing.IN_SANDBOX:
            return AuthDecision(auto=True, summary=_summary(step, crossing))

        signature = self.signature(
            step.tool_ref, step.args, crossing, workspace_root=workspace_root
        )
        if self.is_graduated(signature):
            return AuthDecision(auto=True, summary=_summary(step, crossing))

        staged_args = _stage_args(step, crossing, signature, workspace_root)
        module = _module_for(step.tool_ref)
        # GATE seam verified: ActionStagingService.stage(...) is
        # src/artemis/staging/service.py:27; store.get(action_id) is line 60.
        action = self._staging.stage(
            module,
            step.tool_ref,
            staged_args,
            _summary(step, crossing),
            ttl=self._stage_ttl,
        )
        return AuthDecision(
            auto=False,
            pending=PendingActionRef(action.id),
            summary=_summary(step, crossing),
        )

    def graduate(self, action_id: str) -> bool:
        """Allowlist only a staged action that is already terminally approved."""
        action = self._staging.store.get(action_id)
        if action.status is not ActionStatus.APPROVED:
            return False

        metadata = _metadata_from_action(action)
        if metadata is None:
            return False

        tool_ref, crossing, workspace_root, staged_signature = metadata
        clean_args = _clean_args(action.args)
        recomputed = self.signature(tool_ref, clean_args, crossing, workspace_root=workspace_root)
        if recomputed != staged_signature:
            return False

        self._insert_allowlist(recomputed, tool_ref)
        return True

    def is_graduated(self, signature: str) -> bool:
        """Return whether ``signature`` has an owner-approved allowlist row."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_allowlist WHERE signature = ?",
                (signature,),
            ).fetchone()
        return row is not None

    def signature(
        self,
        tool_ref: str,
        args: dict[str, str | int | float | bool],
        crossing: Crossing,
        *,
        workspace_root: Path,
    ) -> str:
        """Hash the pinned canonical tuple for this action and crossing."""
        kind = _action_kind(args)
        if kind == "network":
            canonical: object = (
                "network",
                _network_host(args),
                _network_port(args),
                _network_protocol(args),
            )
        elif kind == "file":
            target = _primary_file_target(args)
            if target is None:
                canonical = ("unknown", _stable_args(args))
            else:
                canonical = (
                    "file",
                    str(_path_from_arg(target, workspace_root.resolve()).resolve(strict=False)),
                )
        else:
            canonical = (
                "command",
                _argv_tuple(args, workspace_root),
                _env_tuple(args),
            )

        payload = (tool_ref, crossing.value, canonical)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _db_path(self) -> Path:
        return paths.scope_dir(self._settings, OWNER_PRIVATE) / "agentic" / "agent_allowlist.db"

    def _connect(self) -> sqlite3.Connection:
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(db_path, key.as_hex())
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_allowlist ("
            "signature TEXT PRIMARY KEY, "
            "tool_ref TEXT NOT NULL, "
            "approved_at TEXT NOT NULL)"
        )
        return conn

    def _insert_allowlist(self, signature: str, tool_ref: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO agent_allowlist (signature, tool_ref, approved_at) "
                "VALUES (?, ?, ?)",
                (signature, tool_ref, datetime.now(UTC).isoformat()),
            )


def _is_disposable(step: PlanStep) -> bool:
    return step.args.get("disposable") is True


def _declares_network(step: PlanStep) -> bool:
    args = step.args
    if args.get("network") is True:
        return True
    return any(key in args for key in ("host", "port", "protocol", "url"))


def _write_targets(step: PlanStep) -> tuple[str, ...]:
    keys = ("write_target", "target", "path", "file_path")
    return tuple(str(step.args[key]) for key in keys if key in step.args)


def _primary_file_target(args: dict[str, str | int | float | bool]) -> str | None:
    targets = _write_targets(
        PlanStep(id="sig", description="sig", tool_ref="sig", args=args, verify="sig")
    )
    return targets[0] if targets else None


def _path_from_arg(value: str, workspace_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return workspace_root / path


def _action_kind(args: dict[str, str | int | float | bool]) -> str:
    if (
        any(key in args for key in ("host", "port", "protocol", "url"))
        or args.get("network") is True
    ):
        return "network"
    if any(key in args for key in ("write_target", "target", "path", "file_path")):
        return "file"
    return "command"


def _argv_tuple(args: dict[str, str | int | float | bool], workspace_root: Path) -> tuple[str, ...]:
    raw = args.get("argv")
    if raw is None:
        raw = args.get("command", args.get("cmd", args.get("executable", "")))
    parts = _split_argv(str(raw))
    if not parts:
        return ()
    executable = Path(parts[0])
    if executable.is_absolute():
        normalized_head = str(executable.resolve(strict=False))
    else:
        normalized_head = str((workspace_root.resolve() / executable).resolve(strict=False))
    return (normalized_head, *parts[1:])


def _split_argv(raw: str) -> tuple[str, ...]:
    stripped = raw.strip()
    if not stripped:
        return ()
    if stripped.startswith("["):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return tuple(shlex.split(stripped))
        if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
            return tuple(decoded)
    return tuple(shlex.split(stripped))


def _env_tuple(args: dict[str, str | int | float | bool]) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for key, value in args.items():
        if key.startswith("env."):
            values.append((key.removeprefix("env."), str(value)))
        elif key.startswith("env_"):
            values.append((key.removeprefix("env_"), str(value)))
    return tuple(sorted(values))


def _network_host(args: dict[str, str | int | float | bool]) -> str:
    if "url" in args:
        parsed = urlparse(str(args["url"]))
        if parsed.hostname:
            return parsed.hostname.lower()
    return str(args.get("host", "")).strip().lower()


def _network_port(args: dict[str, str | int | float | bool]) -> int:
    if "port" in args:
        return int(args["port"])
    if "url" in args:
        parsed = urlparse(str(args["url"]))
        if parsed.port is not None:
            return parsed.port
        if parsed.scheme == "https":
            return 443
    return 80


def _network_protocol(args: dict[str, str | int | float | bool]) -> str:
    if "protocol" in args:
        return str(args["protocol"]).strip().lower()
    if "url" in args:
        parsed = urlparse(str(args["url"]))
        if parsed.scheme:
            return parsed.scheme.lower()
    return "http"


def _stable_args(args: dict[str, str | int | float | bool]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in args.items()))


def _summary(step: PlanStep, crossing: Crossing) -> str:
    return f"{crossing.value}: {step.tool_ref}"


def _module_for(tool_ref: str) -> str:
    return tool_ref.split(".", 1)[0]


def _stage_args(
    step: PlanStep,
    crossing: Crossing,
    signature: str,
    workspace_root: Path,
) -> dict[str, object]:
    args: dict[str, object] = dict(step.args)
    args["__authority_crossing"] = crossing.value
    args["__authority_signature"] = signature
    args["__authority_tool_ref"] = step.tool_ref
    args["__authority_workspace_root"] = str(workspace_root)
    return args


def _clean_args(args: dict[str, object]) -> dict[str, str | int | float | bool]:
    clean: dict[str, str | int | float | bool] = {}
    for key, value in args.items():
        if key in _AUTH_META_ARGS:
            continue
        if isinstance(value, str | int | float | bool):
            clean[key] = value
    return clean


def _metadata_from_action(action: PendingAction) -> tuple[str, Crossing, Path, str] | None:
    tool_ref = action.args.get("__authority_tool_ref")
    crossing = action.args.get("__authority_crossing")
    workspace_root = action.args.get("__authority_workspace_root")
    signature = action.args.get("__authority_signature")
    if not isinstance(tool_ref, str):
        return None
    if not isinstance(crossing, str):
        return None
    if not isinstance(workspace_root, str):
        return None
    if not isinstance(signature, str):
        return None
    try:
        parsed_crossing = Crossing(crossing)
    except ValueError:
        return None
    return tool_ref, parsed_crossing, Path(workspace_root), signature
