"""Shared subprocess helpers for CLI-backed providers."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence

from artemis.types import Message

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
    argv: list[str], *, stdin: bytes, env: Mapping[str, str] | None = None
) -> tuple[int, bytes, bytes]:
    """Run argv, feed stdin, return (returncode, stdout, stderr).

    ``env``, if given, fully replaces the child environment.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env) if env is not None else None,
    )
    stdout, stderr = await process.communicate(stdin)
    return (process.returncode or 0, stdout, stderr)
