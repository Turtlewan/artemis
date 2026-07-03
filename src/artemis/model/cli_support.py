"""Shared subprocess helpers for CLI-backed providers."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Mapping, Sequence

import psutil

from artemis.types import Message

# Ceiling on a single CLI model call. Generous (authoring a full capability takes minutes) but
# finite, so a wedged CLI fails over instead of hanging its caller forever.
DEFAULT_TIMEOUT_S = 300.0

_QUOTA_RE = re.compile(
    r"(rate.?limit|quota|usage limit|weekly limit|too many requests|\b429\b|exceeded.*limit"
    r"|limit.*reached)",
    re.IGNORECASE,
)


def render_messages(messages: Sequence[Message]) -> str:
    return "\n\n".join(f"{message.role.upper()}:\n{message.content}" for message in messages)


def is_quota_signal(text: str) -> bool:
    return bool(_QUOTA_RE.search(text))


async def run_cli(
    argv: list[str],
    *,
    stdin: bytes,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> tuple[int, bytes, bytes]:
    """Run argv, feed stdin, return (returncode, stdout, stderr).

    ``env``, if given, fully replaces the child environment. A call exceeding ``timeout``
    seconds has its WHOLE process tree killed (npm shims spawn the real binary as a
    grandchild, so killing only the direct child would orphan it) and raises ``TimeoutError``.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env) if env is not None else None,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout=timeout)
    except TimeoutError:
        _kill_process_tree(process.pid)
        with contextlib.suppress(OSError):
            process.kill()
        await process.wait()
        raise
    return (process.returncode or 0, stdout, stderr)


def _kill_process_tree(pid: int) -> None:
    """Best-effort kill of ``pid`` and all its descendants. Never raises."""
    try:
        root = psutil.Process(pid)
        procs = [*root.children(recursive=True), root]
    except psutil.Error:
        return
    for proc in procs:
        with contextlib.suppress(psutil.Error):
            proc.kill()
