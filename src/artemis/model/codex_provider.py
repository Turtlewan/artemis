"""Codex CLI-backed model provider."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import psutil

import artemis.model.cli_support as cli_support
from artemis.model.errors import ProviderError, ProviderUnavailableError, QuotaExhaustedError
from artemis.model.schema_norm import to_strict_schema
from artemis.types import Message

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


class RawProvider(Protocol):
    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> str:
        """Generate final assistant text."""
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
    ) -> str:
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
                returncode, _stdout, stderr = await cli_support.run_cli(
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
            return output_path.read_text(encoding="utf-8").strip()

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
            "-o",
            str(output_path),
        ]
        if schema_path is not None:
            argv.extend(["--output-schema", str(schema_path)])
        argv.append("-")
        return argv
