"""Claude CLI teacher adapter for recipe distillation.

The adapter is intentionally teacher-only. It shells out to the authenticated
``claude`` subscription CLI with a sanitized environment, validates structured
output, retries once with a repair prompt, and then fails without producing a
candidate if the response is still malformed.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator, Sequence
from typing import cast

from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Vector


class TeacherMalformedResponseError(Exception):
    """Raised when the teacher cannot produce schema-valid JSON."""


class ClaudeCliModelPort:
    """ModelPort adapter backed by ``claude -p --output-format json``."""

    def __init__(self) -> None:
        exe = shutil.which("claude")
        if exe is None:
            raise RuntimeError("claude CLI not found on PATH")
        self._exe = exe

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """Run a teacher completion through the Claude CLI."""
        del temperature, max_tokens
        if role != "teacher":
            raise NotImplementedError("ClaudeCliModelPort only supports role='teacher'")

        prompt = _prompt_from_messages(messages)
        if response_schema is None:
            result, model_id = await self._run_claude(prompt)
            return ModelResponse(text=result, origin="cloud", model_id=model_id)

        result, model_id = await self._run_claude(prompt)
        if _schema_valid_json(result, response_schema):
            return ModelResponse(text=result, origin="cloud", model_id=model_id)

        repair_prompt = (
            f"{prompt}\n\nYour prior response did not match this JSON schema:\n"
            f"{json.dumps(response_schema, sort_keys=True)}\n"
            "Return only repaired JSON."
        )
        repaired, repaired_model_id = await self._run_claude(repair_prompt)
        if _schema_valid_json(repaired, response_schema):
            return ModelResponse(text=repaired, origin="cloud", model_id=repaired_model_id)
        raise TeacherMalformedResponseError("teacher returned malformed structured output")

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Streaming is not supported by the Claude CLI teacher adapter."""
        del role, messages, temperature
        raise NotImplementedError("ClaudeCliModelPort does not support streaming")

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        """Embedding is not supported by the Claude CLI teacher adapter."""
        del role, texts
        raise NotImplementedError("ClaudeCliModelPort does not support embedding")

    async def _run_claude(self, prompt: str) -> tuple[str, str]:
        proc = await asyncio.create_subprocess_exec(
            self._exe,
            "-p",
            prompt,
            "--output-format",
            "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_sanitized_env(),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"claude CLI failed: {detail}")
        payload = _json_object(stdout.decode("utf-8", errors="replace"))
        if payload.get("is_error") is True:
            raise RuntimeError("claude CLI returned is_error=true")
        result = payload.get("result")
        if not isinstance(result, str):
            raise RuntimeError("claude CLI response missing string result")
        model = payload.get("model")
        model_id = model if isinstance(model, str) else "claude-cli"
        return result, model_id


def _prompt_from_messages(messages: Sequence[Message]) -> str:
    return "\n\n".join(f"{message.role}: {message.content}" for message in messages)


def _sanitized_env() -> dict[str, str]:
    allowed = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE")
    return {key: value for key in allowed if (value := os.environ.get(key)) is not None}


def _json_object(text: str) -> dict[str, object]:
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise RuntimeError("claude CLI output must be a JSON object")
    return cast(dict[str, object], loaded)


def _schema_valid_json(text: str, schema: dict[str, object]) -> bool:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return False
    return _conforms_to_schema(loaded, schema)


def _conforms_to_schema(value: object, schema: dict[str, object]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return False
        value_dict = cast(dict[str, object], value)
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value_dict:
                    return False
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, property_schema in properties.items():
                if not isinstance(key, str) or key not in value_dict:
                    continue
                if isinstance(property_schema, dict) and not _conforms_to_schema(
                    value_dict[key], cast(dict[str, object], property_schema)
                ):
                    return False
        return True
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return (isinstance(value, int | float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "array":
        return isinstance(value, list)
    enum = schema.get("enum")
    if isinstance(enum, list):
        return value in enum
    return True
