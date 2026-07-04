"""Codex CLI-backed model provider."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psutil

import artemis.model.cli_support as cli_support
from artemis.model.errors import ProviderError, ProviderUnavailableError, QuotaExhaustedError
from artemis.model.schema_norm import to_strict_schema
from artemis.types import Message, Usage

# Stamped into the environment of every codex process Artemis spawns (children inherit it), so
# the reaper can tell Artemis's own strays from foreign codex runs (e.g. the owner's parallel
# builds), which must NEVER be touched.
CODEX_SPAWN_MARKER = "ARTEMIS_CODEX_CALL"

# A marked codex process older than this outlived any legitimate call (calls are killed at
# DEFAULT_TIMEOUT_S) and is a stray from a crashed run -- safe to reap.
REAP_MIN_AGE_S = 900.0


def reap_stale_codex(*, max_age_s: float = REAP_MIN_AGE_S) -> list[int]:
    """Kill stray codex processes Artemis itself spawned; return the reaped PIDs.

    Only processes carrying CODEX_SPAWN_MARKER in their environment are candidates -- foreign
    codex processes are never killed. Best-effort: any per-process error skips that process,
    and the function never raises.
    """
    killed: list[int] = []
    now = time.time()
    try:
        procs = list(psutil.process_iter(["name", "create_time"]))
    except psutil.Error:
        return killed
    for proc in procs:
        try:
            name = (proc.info.get("name") or "").lower()
            if not name.startswith("codex"):
                continue
            created = proc.info.get("create_time")
            if created is None or now - created < max_age_s:
                continue
            if proc.environ().get(CODEX_SPAWN_MARKER) != "1":
                continue
            proc.kill()
            killed.append(proc.pid)
        except (psutil.Error, OSError):
            continue
    return killed


@dataclass(frozen=True)
class Generation:
    """A raw provider reply plus parsed token usage.

    Providers that don't parse usage return a plain ``str`` instead (covariant with
    ``str | Generation``) and the client fills zeros.
    """

    text: str
    usage: Usage


class RawProvider(Protocol):
    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> str | Generation:
        """Generate final assistant text, optionally with parsed usage."""
        ...


class CodexProviderError(ProviderError):
    def __init__(self, returncode: int, stderr_excerpt: str) -> None:
        self.returncode = returncode
        self.stderr_excerpt = stderr_excerpt
        super().__init__(f"Codex CLI exited with {returncode}: {stderr_excerpt}")


class CodexProvider:
    def __init__(
        self,
        *,
        binary: str = "codex",
        model_default: str = "gpt-5.5",
        timeout: float = cli_support.DEFAULT_TIMEOUT_S,
    ) -> None:
        self._binary = shutil.which(binary) or binary
        self._model_default = model_default
        self._timeout = timeout

    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> Generation:
        reap_stale_codex()
        model_id = model or self._model_default
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_path = temp_path / "output.txt"
            schema_path: Path | None = None
            if schema is not None:
                schema_path = temp_path / "schema.json"
                schema_path.write_text(json.dumps(to_strict_schema(schema)), encoding="utf-8")

            argv = self._build_argv(
                model=model_id, output_path=output_path, schema_path=schema_path
            )
            try:
                returncode, stdout, stderr = await cli_support.run_cli(
                    argv,
                    stdin=cli_support.render_messages(messages).encode("utf-8"),
                    env={**os.environ, CODEX_SPAWN_MARKER: "1"},
                    timeout=self._timeout,
                )
            except TimeoutError as exc:
                raise ProviderUnavailableError(
                    "codex", f"call timed out after {int(self._timeout)}s; process tree killed"
                ) from exc
            stderr_text = stderr.decode("utf-8", errors="replace")
            if returncode != 0:
                excerpt = stderr_text[:2000]
                if cli_support.is_quota_signal(stderr_text):
                    raise QuotaExhaustedError("codex", excerpt)
                raise CodexProviderError(returncode or 1, excerpt)
            text = output_path.read_text(encoding="utf-8").strip()
            usage = _parse_codex_usage(stdout.decode("utf-8", errors="replace"))
            return Generation(text=text, usage=usage)

    def _build_argv(
        self,
        *,
        model: str,
        output_path: Path,
        schema_path: Path | None,
    ) -> list[str]:
        argv = [
            self._binary,
            "exec",
            "-m",
            model,
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--json",
            "-o",
            str(output_path),
        ]
        if schema_path is not None:
            argv.extend(["--output-schema", str(schema_path)])
        argv.append("-")
        return argv


def _parse_codex_usage(stdout_text: str) -> Usage:
    """Best-effort token totals from the codex ``--json`` JSONL stream; fail-soft to zeros.

    Scans each line for a token-usage object (prefers a ``total_token_usage`` block, else any object
    with integer input_tokens/output_tokens) and keeps the LAST match so cumulative end-of-run
    totals win. An empty/unknown stream yields zeros -- never raises.
    """
    best: Usage | None = None
    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = _find_token_usage(event)
        if found is not None:
            best = found
    return best or Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _find_token_usage(node: object) -> Usage | None:
    if isinstance(node, dict):
        total = node.get("total_token_usage")
        if isinstance(total, dict):
            pair = _usage_from_pair(total)
            if pair is not None:
                return pair
        pair = _usage_from_pair(node)
        if pair is not None:
            return pair
        for value in node.values():
            nested = _find_token_usage(value)
            if nested is not None:
                return nested
    elif isinstance(node, list):
        for item in node:
            nested = _find_token_usage(item)
            if nested is not None:
                return nested
    return None


def _usage_from_pair(node: dict[str, object]) -> Usage | None:
    """Disqualify malformed negative token fields, degrading to zeros instead of garbage."""
    inp = node.get("input_tokens")
    out = node.get("output_tokens")
    if (
        isinstance(inp, int)
        and not isinstance(inp, bool)
        and inp >= 0
        and isinstance(out, int)
        and not isinstance(out, bool)
        and out >= 0
    ):
        total = node.get("total_tokens")
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            total_tokens = total
        else:
            total_tokens = inp + out
        return Usage(prompt_tokens=inp, completion_tokens=out, total_tokens=total_tokens)
    return None
