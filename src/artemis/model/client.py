"""ModelPort implementation backed by a raw provider."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import jsonschema  # type: ignore[import-untyped]

from artemis.model.codex_provider import Generation, RawProvider
from artemis.types import Message, ModelResponse, Usage


class ModelOutputError(RuntimeError):
    """Raised when a provider never returns valid schema-conforming JSON."""


class ModelClient:
    def __init__(
        self,
        provider: RawProvider,
        *,
        model_default: str = "gpt-5.5",
        max_reasks: int = 2,
    ) -> None:
        self._provider = provider
        self._model_default = model_default
        self._max_reasks = max_reasks

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """Complete once. ``temperature`` and ``max_tokens`` are accepted but unused by Codex."""
        del temperature, max_tokens
        model_id = model or self._model_default

        if response_schema is None:
            raw = await self._provider.generate(messages=messages, model=model_id, schema=None)
            text, usage = _split(raw)
            return ModelResponse(
                text=text,
                model_id=model_id,
                structured=None,
                finish_reason="stop",
                usage=usage,
            )

        attempt_messages = list(messages)
        last_error: Exception | None = None
        for _attempt in range(self._max_reasks + 1):
            raw = await self._provider.generate(
                messages=attempt_messages,
                model=model_id,
                schema=response_schema,
            )
            text, usage = _split(raw)
            try:
                parsed = json.loads(text)
                jsonschema.validate(instance=parsed, schema=response_schema)
                structured = _ensure_structured(parsed)
                return ModelResponse(
                    text=text,
                    model_id=model_id,
                    structured=structured,
                    finish_reason="stop",
                    usage=usage,
                )
            except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
                last_error = exc
                attempt_messages.append(
                    Message(
                        role="user",
                        content=(
                            "Your previous reply was not valid against the schema: "
                            f"{exc}. Return only valid JSON."
                        ),
                    )
                )

        raise ModelOutputError("Provider did not return valid structured output") from last_error


def _split(result: str | Generation) -> tuple[str, Usage]:
    if isinstance(result, Generation):
        return result.text, result.usage
    return result, Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _ensure_structured(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise ModelOutputError("Structured model output must be a JSON object")
