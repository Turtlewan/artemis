"""Search provider adapters for reach-out web primitives."""

from __future__ import annotations

import json
import logging
from typing import Protocol, TypeAlias, cast

import httpx
from pydantic import BaseModel, ConfigDict

from artemis.reachout.egress import EgressPolicy

_log = logging.getLogger(__name__)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class SearchError(Exception):
    """Raised when the search provider returns a non-success response."""


class SearchHit(BaseModel):
    """A single web search result."""

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    snippet: str


class SearchProvider(Protocol):
    """Protocol for web search adapters."""

    async def search(self, query: str, *, count: int = 8) -> list[SearchHit]:
        """Return search hits for a query."""
        ...


class TavilySearch:
    """Tavily-backed search adapter."""

    def __init__(
        self,
        api_key: str,
        egress: EgressPolicy,
        *,
        base_url: str = "https://api.tavily.com/search",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._egress = egress
        self._base_url = base_url
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            event_hooks={"request": [self._redact_secrets_for_hooks]}
        )

    async def search(self, query: str, *, count: int = 8) -> list[SearchHit]:
        """Search Tavily and return normalized hits."""
        self._egress.check(self._base_url)
        response = await self._http.post(
            self._base_url,
            json={"api_key": self._api_key, "query": query, "max_results": count},
        )
        if not 200 <= response.status_code < 300:
            raise SearchError(f"tavily returned {response.status_code}")
        payload = cast(JsonObject, response.json())
        results = payload.get("results", [])
        if not isinstance(results, list):
            return []
        hits: list[SearchHit] = []
        for item in results:
            if isinstance(item, dict):
                item_obj = cast(dict[str, object], item)
                hits.append(
                    SearchHit(
                        title=_string_field(item_obj, "title"),
                        url=_string_field(item_obj, "url"),
                        snippet=_string_field(item_obj, "content"),
                    )
                )
        return hits

    async def aclose(self) -> None:
        """Close the internal HTTP client if this adapter created it."""
        if self._owns_http:
            await self._http.aclose()

    @staticmethod
    async def _redact_secrets_for_hooks(request: httpx.Request) -> None:
        """Attach a hook-safe request snapshot with body and header secrets redacted."""
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"authorization", "x-subscription-token"}
        }
        try:
            body: JsonValue = _redact_json(cast(JsonValue, json.loads(request.content)))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = "<non-json>"
        request.extensions["artemis_safe_snapshot"] = {"headers": headers, "body": body}


def _redact_json(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: "***"
            if key.lower() in {"api_key", "token", "authorization"}
            else _redact_json(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    return value


def _string_field(item: dict[str, object], key: str) -> str:
    value = item.get(key, "")
    if isinstance(value, str):
        return value
    return ""
