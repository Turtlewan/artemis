"""Codex CLI-backed model provider."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import artemis.model.cli_support as cli_support
from artemis.model.errors import ProviderError, QuotaExhaustedError
from artemis.model.schema_norm import to_strict_schema
from artemis.types import Message


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
    def __init__(self, *, binary: str = "codex", model_default: str = "gpt-5.5") -> None:
        self._binary = shutil.which(binary) or binary
        self._model_default = model_default

    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> str:
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
            returncode, _stdout, stderr = await cli_support.run_cli(
                argv, stdin=cli_support.render_messages(messages).encode("utf-8")
            )
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
