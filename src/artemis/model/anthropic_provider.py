"""Anthropic Messages API-backed raw model provider."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import cast

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message as AnthropicMessage
from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam

import artemis.model.cli_support as cli_support
from artemis.model.errors import ProviderUnavailableError, QuotaExhaustedError
from artemis.types import Message


class AnthropicAPIProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_default: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self._model_default = model_default
        self._max_tokens = max_tokens
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if client is not None:
            self._client: AsyncAnthropic | None = client
        elif key is not None:
            self._client = AsyncAnthropic(api_key=key)
        else:
            self._client = None

    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> str:
        if self._client is None:
            raise ProviderUnavailableError("anthropic_api", "no API key")

        system_text, mapped_messages = _map_messages(messages)
        model_id = model or self._model_default
        try:
            response = await self._create_message(
                model=model_id,
                system_text=system_text,
                messages=mapped_messages,
                schema=schema,
            )
        except anthropic.RateLimitError as exc:
            raise QuotaExhaustedError("anthropic_api", _excerpt(str(exc))) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderUnavailableError("anthropic_api", _excerpt(str(exc))) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError("anthropic_api", _excerpt(str(exc))) from exc
        except anthropic.APIStatusError as exc:
            detail = _excerpt(str(exc))
            if exc.status_code == 429 or cli_support.is_quota_signal(detail):
                raise QuotaExhaustedError("anthropic_api", detail) from exc
            raise ProviderUnavailableError("anthropic_api", detail) from exc
        except anthropic.APIError as exc:
            detail = _excerpt(str(exc))
            if cli_support.is_quota_signal(detail):
                raise QuotaExhaustedError("anthropic_api", detail) from exc
            raise ProviderUnavailableError("anthropic_api", detail) from exc

        if schema is not None:
            return _extract_tool_json(response)
        return _extract_text(response)

    async def _create_message(
        self,
        *,
        model: str,
        system_text: str | None,
        messages: list[MessageParam],
        schema: dict | None,  # type: ignore[type-arg]
    ) -> AnthropicMessage:
        if self._client is None:
            raise ProviderUnavailableError("anthropic_api", "no API key")

        if schema is None:
            if system_text is None:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=self._max_tokens,
                    messages=messages,
                )
            else:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=self._max_tokens,
                    system=system_text,
                    messages=messages,
                )
            return response

        tools = [
            cast(
                ToolParam,
                {
                    "name": "emit",
                    "description": "Return the result.",
                    "input_schema": schema,
                },
            )
        ]
        tool_choice = cast(ToolChoiceToolParam, {"type": "tool", "name": "emit"})
        if system_text is None:
            response = await self._client.messages.create(
                model=model,
                max_tokens=self._max_tokens,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        else:
            response = await self._client.messages.create(
                model=model,
                max_tokens=self._max_tokens,
                system=system_text,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        return response


def _map_messages(messages: Sequence[Message]) -> tuple[str | None, list[MessageParam]]:
    system_parts: list[str] = []
    mapped: list[MessageParam] = []
    for message in messages:
        if message.role == "system":
            system_parts.append(message.content)
        else:
            mapped.append({"role": message.role, "content": message.content})
    return ("\n\n".join(system_parts) if system_parts else None), mapped


def _extract_tool_json(response: AnthropicMessage) -> str:
    for block in response.content:
        if block.type == "tool_use" and block.name == "emit":
            return json.dumps(block.input)
    raise ProviderUnavailableError("anthropic_api", "response missing emit tool_use block")


def _extract_text(response: AnthropicMessage) -> str:
    parts = [block.text for block in response.content if block.type == "text"]
    return "".join(parts).strip()


def _excerpt(text: str) -> str:
    return text[:2000]
