"""Claude Code CLI-backed raw model provider."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

import artemis.model.cli_support as cli_support
from artemis.model.errors import ProviderUnavailableError, QuotaExhaustedError
from artemis.model.codex_provider import Generation
from artemis.types import Message, Usage


class ClaudeCodeProvider:
    def __init__(
        self,
        *,
        binary: str = "claude",
        model_default: str = "sonnet",
        timeout: float = cli_support.DEFAULT_TIMEOUT_S,
    ) -> None:
        self._binary = shutil.which(binary) or binary
        self._model_default = model_default
        self._timeout = timeout
        self._cfg_dir: Path | None = None

    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> Generation:
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
            "--exclude-dynamic-system-prompt-sections",
            "--tools",
            "",
        ]
        try:
            returncode, stdout, stderr = await self._run_cli(argv)
        except TimeoutError as exc:
            raise ProviderUnavailableError(
                "claude_code",
                f"call timed out after {int(self._timeout)}s; process tree killed",
            ) from exc
        text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        if returncode != 0:
            combined = stderr_text + text
            if cli_support.is_quota_signal(combined):
                raise QuotaExhaustedError("claude_code", _excerpt(stderr_text))
            raise ProviderUnavailableError("claude_code", _excerpt(stderr_text))
        result = _extract_result(text)
        # CLI models wrap structured output in a whole-output ```json fence; strip it so the
        # caller's json.loads / model_validate_json sees clean JSON. Only for schema calls, and
        # only when the ENTIRE output is one fenced block (leaves prose / inline code untouched).
        final_text = _strip_code_fence(result) if schema is not None else result
        return Generation(text=final_text, usage=_extract_usage(text))

    async def _run_cli(self, argv: list[str]) -> tuple[int, bytes, bytes]:
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self._ensure_clean_config_dir())}
        return await cli_support.run_cli(argv, stdin=b"", env=env, timeout=self._timeout)

    def _ensure_clean_config_dir(self) -> Path:
        """Return a private Claude config dir containing only a fresh credentials copy.

        Claude CLI reads can be polluted by user-level CLAUDE.md or settings files. The per-call
        guard removes anything except credentials before invocation, and the mtime check avoids
        rewriting the live-token copy unless the source token changed.
        """
        source = Path.home() / ".claude" / ".credentials.json"
        if not source.exists():
            raise ProviderUnavailableError("claude_code", "no credentials for clean-context read")

        if self._cfg_dir is None:
            # mkdtemp gives an unpredictable, per-process path (closes CWE-377). The chmod bits are
            # POSIX-only defense-in-depth; on Windows chmod only toggles read-only (no ACLs), so the
            # unpredictable path — not the mode — is the load-bearing protection there.
            self._cfg_dir = Path(tempfile.mkdtemp(prefix="artemis-claude-clean-"))
            self._cfg_dir.chmod(0o700)
            atexit.register(shutil.rmtree, self._cfg_dir, ignore_errors=True)

        self._remove_config_poison(self._cfg_dir)
        dest = self._cfg_dir / ".credentials.json"
        if self._credentials_need_copy(source, dest):
            self._copy_credentials_atomic(source, dest)
        return self._cfg_dir

    def _remove_config_poison(self, cfg_dir: Path) -> None:
        for entry in cfg_dir.iterdir():
            # Keep only the REAL creds file. A symlinked ".credentials.json" is poison (it could
            # point at attacker-writable content the mtime guard would then trust) — fall through
            # and remove it, forcing a fresh copy of the real token.
            if entry.name == ".credentials.json" and not entry.is_symlink():
                continue
            try:
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError as exc:
                raise ProviderUnavailableError(
                    "claude_code", "unable to clean Claude config dir"
                ) from exc

    def _credentials_need_copy(self, source: Path, dest: Path) -> bool:
        if not dest.exists():
            return True
        return source.stat().st_mtime_ns > dest.stat().st_mtime_ns

    def _copy_credentials_atomic(self, source: Path, dest: Path) -> None:
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=dest.parent,
                prefix=".credentials.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                with source.open("rb") as source_file:
                    shutil.copyfileobj(source_file, tmp_file)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            tmp_path.chmod(0o600)
            os.replace(tmp_path, dest)
            dest.chmod(0o600)
        except OSError as exc:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            raise ProviderUnavailableError(
                "claude_code", "unable to copy credentials for clean-context read"
            ) from exc


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


def _extract_usage(stdout: str) -> Usage:
    """Read the ``usage`` sibling of the claude JSON envelope; fail-soft to zeros.

    Cache tokens stay distinct: prompt is non-cached input only; total is all input plus output.
    """
    zero = Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return zero
    if not isinstance(value, dict):
        return zero
    raw = value.get("usage")
    if not isinstance(raw, dict):
        return zero

    def _int(key: str) -> int:
        v = raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0

    prompt = _int("input_tokens")
    cache_read = _int("cache_read_input_tokens")
    cache_creation = _int("cache_creation_input_tokens")
    completion = _int("output_tokens")
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + cache_read + cache_creation + completion,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
    )


def _strip_code_fence(text: str) -> str:
    """Return the inner content if the whole output is a single ```-fenced block, else unchanged.

    CLI models often wrap a structured JSON reply in a ```json ... ``` fence, which breaks a
    downstream json.loads. Only strips when the ENTIRE trimmed text is one fenced block, so a
    prose answer containing an inline code block is left intact.
    """
    stripped = text.strip()
    if len(stripped) < 6 or not stripped.startswith("```") or not stripped.endswith("```"):
        return text
    inner = stripped[3:-3]
    newline = inner.find("\n")
    if newline != -1:
        first_line = inner[:newline].strip()
        if first_line == "" or first_line.isalnum():  # optional language tag (e.g. "json")
            inner = inner[newline + 1 :]
    return inner.strip()


def _excerpt(text: str) -> str:
    return text[:2000]
