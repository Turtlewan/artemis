"""CodexModelPort - reasoning via the Codex CLI on the ChatGPT subscription.

Runs ``codex exec`` non-interactively in a read-only, ephemeral sandbox and
reads the final assistant message from the ``-o`` output file. Codex reasoning
is cloud-origin and does not provide embeddings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from artemis.config import Settings, get_settings
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector

logger = logging.getLogger(__name__)

_ROLE_PREFIX = {"system": "[system]", "user": "[user]", "assistant": "[assistant]"}


def _render_prompt(messages: Sequence[Message]) -> str:
    """Flatten role-tagged messages into one Codex prompt."""
    return "\n\n".join(f"{_ROLE_PREFIX.get(m.role, f'[{m.role}]')}\n{m.content}" for m in messages)


class CodexModelPort:
    """ModelPort adapter that reasons via ``codex exec`` on the ChatGPT subscription."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings: Settings = settings or get_settings()
        self._binary = self._settings.codex_binary
        self._model = self._settings.codex_model

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """Run one non-streaming Codex reasoning turn."""
        del role, temperature, max_tokens
        prompt = _render_prompt(messages)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "last.txt"
            args = [
                self._binary,
                "exec",
                "-m",
                self._model,
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color",
                "never",
                "-o",
                str(out),
            ]
            if response_schema is not None:
                schema_path = Path(td) / "schema.json"
                await asyncio.to_thread(schema_path.write_text, json.dumps(response_schema))
                args += ["--output-schema", str(schema_path)]
            args.append("-")

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate(prompt.encode())
            if proc.returncode != 0:
                logger.debug(
                    "codex exec stderr (rc=%s): %s",
                    proc.returncode,
                    stderr.decode(errors="replace")[:300],
                )
                raise RuntimeError(f"codex exec failed (rc={proc.returncode})")
            text = (
                (await asyncio.to_thread(out.read_text, encoding="utf-8")).strip()
                if out.exists()
                else ""
            )

        return ModelResponse(
            text=text,
            finish_reason="stop",
            usage=Usage(0, 0, 0),
            origin="cloud",
            model_id=self._model,
        )

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Yield the full completion once; Codex subscription path has no token stream."""

        async def _one() -> AsyncIterator[str]:
            resp = await self.complete(role=role, messages=messages, temperature=temperature)
            yield resp.text

        return _one()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        """Raise because Codex does not expose embeddings."""
        del role, texts
        raise NotImplementedError("Codex has no embeddings; embeddings stay local (ADR-022).")
