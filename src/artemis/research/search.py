"""Search provider ports and web-search adapters for research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from artemis.research.egress import EgressPolicy


@dataclass(frozen=True)
class SearchHit:
    """A single web-search result."""

    title: str
    url: str
    snippet: str


class SearchError(Exception):
    """Raised when a search provider returns an unusable response."""


class SearchProvider(Protocol):
    """Port for non-sensitive web-search queries."""

    async def search(self, query: str, *, count: int = 8) -> list[SearchHit]:
        """Return search hits for ``query``."""
        ...


async def _strip_auth_for_hooks(request: httpx.Request) -> None:
    """Remove credentials from hook-visible extensions without logging them."""

    request.extensions["artemis_safe_headers"] = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"authorization", "x-subscription-token"}
    }


class BraveSearch:
    """Brave Search adapter.

    Brave web search responses are expected to contain ``web.results[]`` with
    ``title``, ``url``, and ``description`` fields. API keys are supplied by the
    caller and are never read from process environment.
    """

    def __init__(
        self,
        api_key: str,
        egress: EgressPolicy,
        *,
        base_url: str = "https://api.search.brave.com/res/v1/web/search",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._egress = egress
        self._base_url = base_url
        self._http = http

    async def search(self, query: str, *, count: int = 8) -> list[SearchHit]:
        """Return Brave web results for ``query``."""

        self._egress.check(self._base_url)
        client = self._client()
        response = await client.get(
            self._base_url,
            headers={"X-Subscription-Token": self._api_key},
            params={"q": query, "count": count},
        )
        if not 200 <= response.status_code < 300:
            raise SearchError(f"Brave search failed with HTTP {response.status_code}")
        payload = response.json()
        results = payload.get("web", {}).get("results", [])
        if not isinstance(results, list):
            raise SearchError("Brave search returned invalid results")
        hits: list[SearchHit] = []
        for item in results:
            if isinstance(item, dict):
                hits.append(
                    SearchHit(
                        title=str(item.get("title", "")),
                        url=str(item.get("url", "")),
                        snippet=str(item.get("description", "")),
                    )
                )
        return hits

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        self._http = httpx.AsyncClient(event_hooks={"request": [_strip_auth_for_hooks]})
        return self._http


class TavilySearch:
    """Tavily search adapter with caller-supplied API keys."""

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
        self._http = http

    async def search(self, query: str, *, count: int = 8) -> list[SearchHit]:
        """Return Tavily web results for ``query``."""

        self._egress.check(self._base_url)
        client = self._client()
        response = await client.post(
            self._base_url,
            json={"api_key": self._api_key, "query": query, "max_results": count},
        )
        if not 200 <= response.status_code < 300:
            raise SearchError(f"Tavily search failed with HTTP {response.status_code}")
        payload = response.json()
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise SearchError("Tavily search returned invalid results")
        hits: list[SearchHit] = []
        for item in results:
            if isinstance(item, dict):
                hits.append(
                    SearchHit(
                        title=str(item.get("title", "")),
                        url=str(item.get("url", "")),
                        snippet=str(item.get("content", "")),
                    )
                )
        return hits

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        self._http = httpx.AsyncClient(event_hooks={"request": [_strip_auth_for_hooks]})
        return self._http
