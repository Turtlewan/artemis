"""Fetch provider ports and article extraction adapters for research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urljoin, urlparse

import httpx
import trafilatura

from artemis.obs import get_logger
from artemis.research.egress import EgressDenied, EgressPolicy, registrable_domain

logger = get_logger("research.fetch")


@dataclass(frozen=True)
class FetchedContent:
    """Clean text fetched from a URL."""

    url: str
    domain: str
    text: str


class FetchError(Exception):
    """Reserved for callers that need to classify fetch failures."""


class Fetcher(Protocol):
    """Port for bounded web-content retrieval."""

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        """Return clean text for ``url`` without raising on transient failures."""
        ...


class TrafilaturaFetcher:
    """HTTP fetcher using local trafilatura extraction with bounded bytes."""

    def __init__(
        self,
        egress: EgressPolicy,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 8.0,
        max_bytes: int = 5_000_000,
    ) -> None:
        self._egress = egress
        self._http = http
        self._timeout = timeout
        self._max_bytes = max_bytes

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        """Fetch, extract, and truncate article text; degrade to empty text on failure."""

        try:
            final_url, html = await self._download(url)
            text = trafilatura.extract(html) or ""
            if not text:
                raise FetchError("trafilatura extracted no text")
            return FetchedContent(final_url, registrable_domain(final_url), text[:max_chars])
        except Exception as exc:
            logger.warning("fetch_degraded", extra={"host": urlparse(url).hostname or ""})
            if isinstance(exc, EgressDenied):
                raise
            return FetchedContent(url, registrable_domain(url), "")

    async def _download(self, url: str) -> tuple[str, str]:
        current_url = url
        client = self._client()
        for _ in range(6):
            self._egress.check(current_url)
            response = await client.get(current_url)
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location")
                if not location:
                    raise FetchError("redirect missing Location")
                current_url = urljoin(current_url, location)
                self._egress.check(current_url)
                continue
            if not 200 <= response.status_code < 300:
                raise FetchError(f"fetch failed with HTTP {response.status_code}")
            body = await _read_limited(response, self._max_bytes)
            return str(response.url), body.decode(response.encoding or "utf-8", errors="replace")
        raise FetchError("too many redirects")

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        self._http = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
        )
        return self._http


class JinaFetcher:
    """Jina Reader fetcher for pages that benefit from hosted markdown extraction."""

    def __init__(
        self,
        egress: EgressPolicy,
        *,
        api_key: str | None = None,
        base: str = "https://r.jina.ai/",
        http: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._egress = egress
        self._api_key = api_key
        self._base = base
        self._http = http
        self._timeout = timeout

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        """Fetch reader-mode markdown through Jina; degrade to empty text on failure."""

        try:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise FetchError("Jina target must be an absolute https URL")
            self._egress.check(url)
            self._egress.check(self._base)
            headers = {}
            if self._api_key is not None:
                headers["Authorization"] = f"Bearer {self._api_key}"
            response = await self._client().get(
                f"{self._base}{quote(url, safe='')}",
                headers=headers,
            )
            if not 200 <= response.status_code < 300:
                raise FetchError(f"Jina fetch failed with HTTP {response.status_code}")
            return FetchedContent(url, registrable_domain(url), response.text[:max_chars])
        except Exception as exc:
            logger.warning("fetch_degraded", extra={"host": urlparse(url).hostname or ""})
            if isinstance(exc, EgressDenied):
                raise
            return FetchedContent(url, registrable_domain(url), "")

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        self._http = httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        return self._http


class PlaywrightFetcher:
    """Seam for a Playwright-backed fetcher used for JavaScript-locked pages."""

    def __init__(self, egress: EgressPolicy, *, timeout: float = 15.0) -> None:
        self._egress = egress
        self._timeout = timeout

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        """Validate egress and return an empty degraded result until MCP wiring exists."""

        try:
            self._egress.check(url)
        except Exception as exc:
            logger.warning("fetch_degraded", extra={"host": urlparse(url).hostname or ""})
            if isinstance(exc, EgressDenied):
                raise
        return FetchedContent(url, registrable_domain(url), "")


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    total = 0
    chunks: list[bytes] = []
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise FetchError("response exceeded max_bytes")
        chunks.append(chunk)
    return b"".join(chunks)
