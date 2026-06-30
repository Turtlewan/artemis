"""Claude Code CLI-backed raw model provider."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence

import artemis.model.cli_support as cli_support
from artemis.model.errors import ProviderUnavailableError, QuotaExhaustedError
from artemis.types import Message


class ClaudeCodeProvider:
    def __init__(self, *, binary: str = "claude", model_default: str = "sonnet") -> None:
        self._binary = shutil.which(binary) or binary
        self._model_default = model_default

    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> str:
        prompt = cli_support.render_messages(messages)
        if schema is not None:
            prompt += "\n\nReturn ONLY a JSON value conforming to this JSON Schema:\n" + json.dumps(
                schema
            )

        argv = [
            self._binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            model or self._model_default,
        ]
        returncode, stdout, stderr = await cli_support.run_cli(argv, stdin=b"")
        text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        if returncode != 0:
            combined = stderr_text + text
            if cli_support.is_quota_signal(combined):
                raise QuotaExhaustedError("claude_code", _excerpt(stderr_text))
            raise ProviderUnavailableError("claude_code", _excerpt(stderr_text))
        return _extract_result(text)


def _extract_result(stdout: str) -> str:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()
    if isinstance(value, dict):
        result = value.get("result")
        if isinstance(result, str):
            return result
    return stdout.strip()


def _excerpt(text: str) -> str:
    return text[:2000]
