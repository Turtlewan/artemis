from __future__ import annotations

import logging
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict
import trafilatura

from artemis.reachout.egress import EgressDenied, EgressPolicy, registrable_domain

_log = logging.getLogger(__name__)


class FetchedContent(BaseModel):
    """Clean-text extraction result for a fetched URL."""

    model_config = ConfigDict(frozen=True)

    url: str
    domain: str
    text: str


class Fetcher(Protocol):
    """Protocol for clean-text URL fetchers."""

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        """Fetch a URL and return its extracted clean text, truncated to `max_chars`."""
        ...


def _safe_domain(url: str) -> str:
    try:
        return registrable_domain(url)
    except Exception:
        return ""


class _PinnedTransport(httpx.AsyncBaseTransport):
    """Connect to the guard-validated IP while preserving Host and TLS SNI."""

    def __init__(self, egress: EgressPolicy, inner: httpx.AsyncBaseTransport) -> None:
        self._egress = egress
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        ip = self._egress.pin(str(request.url))
        original_host = request.url.host
        request.url = request.url.copy_with(host=ip)
        request.headers["Host"] = original_host
        request.extensions = {**request.extensions, "sni_hostname": original_host}
        return await self._inner.handle_async_request(request)


class TrafilaturaFetcher:
    """Egress-guarded, pinned-IP HTTP fetcher with trafilatura-based clean-text extraction."""

    def __init__(
        self,
        egress: EgressPolicy,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 8.0,
        max_bytes: int = 5_000_000,
    ) -> None:
        self._egress = egress
        self._max_bytes = max_bytes
        if http is not None:
            if http.follow_redirects is not False:
                raise ValueError("Fetcher requires an http client with follow_redirects=False")
            self._http = http
            self._owns_http = False
        else:
            self._http = httpx.AsyncClient(
                transport=_PinnedTransport(egress, httpx.AsyncHTTPTransport()),
                follow_redirects=False,
                timeout=timeout,
            )
            self._owns_http = True

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        """Fetch `url` (bounded redirects, pinned-IP, content-type gated) and extract clean text.

        Never raises past this boundary except `EgressDenied`; other failures degrade to
        empty text.
        """
        try:
            current = url
            for _hop in range(6):
                async with self._http.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        if not location:
                            break
                        location = str(httpx.URL(current).join(location))
                        self._egress.check(location)
                        current = location
                        continue

                    # content-type gate runs on headers alone (before any body is streamed);
                    # media types are case-insensitive, so normalize first (FLAG 7).
                    content_type = response.headers.get("content-type", "").lower()
                    if not (
                        content_type.startswith("text/html")
                        or content_type.startswith("application/xhtml+xml")
                    ):
                        return FetchedContent(url=url, domain=_safe_domain(url), text="")

                    # streaming size cap: abort the moment cumulative bytes exceed max_bytes, so an
                    # oversized (or slow-drip) body from an allowlisted host is never fully buffered.
                    chunks: list[bytes] = []
                    total = 0
                    oversize = False
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self._max_bytes:
                            oversize = True
                            break
                        chunks.append(chunk)
                    if oversize:
                        _log.warning(
                            "fetch_degraded reason=oversize url=%s bytes>%d", url, self._max_bytes
                        )
                        return FetchedContent(url=url, domain=_safe_domain(url), text="")

                    body = b"".join(chunks)
                    html = body.decode(response.encoding or "utf-8", errors="replace")
                    extracted = trafilatura.extract(html) or ""
                    text = extracted[:max_chars]
                    return FetchedContent(url=url, domain=_safe_domain(url), text=text)

            _log.warning("fetch_degraded reason=too_many_redirects url=%s", url)
            return FetchedContent(url=url, domain=_safe_domain(url), text="")
        except EgressDenied:
            raise
        except Exception as exc:
            _log.warning("fetch_degraded reason=%s url=%s", type(exc).__name__, url)
            return FetchedContent(url=url, domain=_safe_domain(url), text="")

    async def aclose(self) -> None:
        """Close the internal HTTP client if this fetcher created it."""
        if self._owns_http:
            await self._http.aclose()
