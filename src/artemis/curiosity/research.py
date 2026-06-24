"""Research port and grounding gate for Curiosity results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import tldextract


@dataclass(frozen=True)
class Source:
    """An external URL source cited by a research result."""

    url: str
    domain: str
    snippet: str


@dataclass(frozen=True)
class ResearchResult:
    """Grounding candidate returned by a Researcher implementation."""

    query: str
    content: str
    sources: list[Source]
    self_generated: bool
    token_usage: int = 0


class Researcher(Protocol):
    """Port for the separate Deep-Research engine."""

    async def research(self, query: str, *, token_cap: int) -> ResearchResult:
        """Return grounded candidate content bounded by ``token_cap``."""
        ...


class StubResearcher:
    """Minimal stub for M7-c; the real Deep-Research engine swaps in later."""

    def __init__(self, result: ResearchResult | None = None) -> None:
        self._result = result
        self.calls: list[tuple[str, int]] = []

    async def research(self, query: str, *, token_cap: int) -> ResearchResult:
        """Return a fixed result shaped to satisfy the grounding gate by default."""

        self.calls.append((query, token_cap))
        if self._result is not None:
            return self._result
        return ResearchResult(
            query=query,
            content="Curiosity stub research result. Replace with the real engine in DR.",
            sources=[
                Source(
                    url="https://example.com/curiosity/source-a",
                    domain="example.com",
                    snippet="Stub source A.",
                ),
                Source(
                    url="https://iana.org/domains/reserved",
                    domain="iana.org",
                    snippet="Stub source B.",
                ),
            ],
            self_generated=False,
            token_usage=0,
        )


class Reachability(Protocol):
    """URL reachability check used by the grounding gate."""

    def is_reachable(self, url: str) -> bool:
        """Return True only for reachable 2xx/3xx external URLs."""
        ...


class HttpReachability:
    """Short-timeout HEAD/GET reachability checker for live use."""

    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self._timeout_seconds = timeout_seconds

    def is_reachable(self, url: str) -> bool:
        """Return True when a URL responds with a 2xx or 3xx status."""

        if not _has_external_scheme(url):
            return False
        for method in ("HEAD", "GET"):
            request = Request(url, method=method, headers={"User-Agent": "artemis-curiosity/1.0"})
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    status = cast(int, response.status)
                    return 200 <= status < 400
            except HTTPError as exc:
                if exc.code == 405 and method == "HEAD":
                    continue
                return False
            except (TimeoutError, URLError, ValueError):
                return False
        return False


class GroundingError(Exception):
    """Reserved for future gate diagnostics; ``grounding_gate`` returns bool."""


def registrable_domain(url: str) -> str:
    """Return the eTLD+1 registrable domain for a URL using the bundled PSL."""

    extracted = tldextract.extract(url)
    return extracted.top_domain_under_public_suffix


def grounding_gate(result: ResearchResult, reachability: Reachability) -> bool:
    """Accept only non-self-generated results with two reachable distinct domains."""

    if result.self_generated:
        return False

    reachable_domains: set[str] = set()
    seen_domains: set[str] = set()
    for source in result.sources:
        if not _has_external_scheme(source.url):
            continue
        domain = registrable_domain(source.url)
        if not domain:
            continue
        seen_domains.add(domain)
        if reachability.is_reachable(source.url):
            reachable_domains.add(domain)

    return len(seen_domains) >= 2 and len(reachable_domains) >= 2


def _has_external_scheme(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
