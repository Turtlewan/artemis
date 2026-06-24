from __future__ import annotations

import logging
import socket
from collections.abc import Callable

import httpx
import pytest

from artemis.research import (
    BraveSearch,
    EgressDenied,
    EgressPolicy,
    FetchedContent,
    SearchError,
    TavilySearch,
    TrafilaturaFetcher,
    registrable_domain,
)

GetAddrInfo = Callable[..., list[tuple[int, int, int, str, tuple[str, int]]]]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(
        host: str,
        port: object,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_egress_allow_deny_log_and_reset(caplog: pytest.LogCaptureFixture) -> None:
    policy = EgressPolicy(frozenset({"api.search.brave.com"}))

    with caplog.at_level(logging.WARNING):
        with pytest.raises(EgressDenied):
            policy.check("https://example.com/p")

    assert "egress_denied" in caplog.text
    assert any(getattr(record, "host", "") == "example.com" for record in caplog.records)

    policy.check("https://api.search.brave.com/res/v1/web/search")
    policy.permit("example.com")
    policy.check("https://example.com/p")
    policy.check("https://www.example.com/p")
    policy.permit("python.org")
    policy.check("https://docs.python.org/3/")

    with pytest.raises(ValueError):
        policy.permit("https://x.com/p")

    policy.reset_dynamic()
    with pytest.raises(EgressDenied):
        policy.check("https://example.com/p")


@pytest.mark.parametrize("address", ["169.254.169.254", "127.0.0.1", "10.0.0.1"])
def test_egress_blocks_private_resolutions(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    def fake_getaddrinfo(
        host: str,
        port: object,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    policy = EgressPolicy(frozenset())
    policy.permit("example.com")

    with pytest.raises(EgressDenied):
        policy.check("https://example.com/p")


def test_egress_blocks_non_https() -> None:
    policy = EgressPolicy(frozenset())
    policy.permit("example.com")

    with pytest.raises(EgressDenied):
        policy.check("http://example.com/p")


@pytest.mark.asyncio
async def test_brave_search_parses_hits_and_blocks_key_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    key = "0123456789abcdef0123456789abcdef"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == key
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": f"Title {index}",
                            "url": f"https://example.com/{index}",
                            "description": f"Snippet {index}",
                        }
                        for index in range(3)
                    ]
                }
            },
        )

    policy = EgressPolicy(frozenset({"api.search.brave.com"}))
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.DEBUG):
        hits = await BraveSearch(key, policy, http=http).search("q", count=3)

    assert len(hits) == 3
    assert hits[0].title == "Title 0"
    assert key not in caplog.text
    await http.aclose()


@pytest.mark.asyncio
async def test_search_errors_on_non_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    policy = EgressPolicy(frozenset({"api.search.brave.com"}))
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(SearchError):
        await BraveSearch("test-key", policy, http=http).search("q", count=3)

    await http.aclose()


@pytest.mark.asyncio
async def test_tavily_search_parses_hits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode()
        assert "test-key" in payload
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Tavily title",
                        "url": "https://example.com/t",
                        "content": "Tavily content",
                    }
                ]
            },
        )

    policy = EgressPolicy(frozenset({"api.tavily.com"}))
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    hits = await TavilySearch("test-key", policy, http=http).search("q", count=1)

    assert hits == [type(hits[0])("Tavily title", "https://example.com/t", "Tavily content")]
    await http.aclose()


@pytest.mark.asyncio
async def test_trafilatura_fetch_extracts_truncates_and_sets_domain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            html="""
            <html><head><title>Article</title></head><body>
            <article><h1>Article title</h1><p>This is a long clean paragraph for extraction.</p></article>
            </body></html>
            """,
            request=request,
        )

    url = "https://sub.www.example.co.uk/article"
    policy = EgressPolicy(frozenset())
    policy.permit("example.co.uk")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

    result = await TrafilaturaFetcher(policy, http=http).fetch(url, max_chars=30)

    assert isinstance(result, FetchedContent)
    assert result.text
    assert len(result.text) <= 30
    assert result.domain == "example.co.uk"
    assert result.domain == registrable_domain("https://other.example.co.uk/path")
    await http.aclose()


@pytest.mark.asyncio
async def test_trafilatura_redirect_to_internal_ip_is_denied() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "https://127.0.0.1/private"}, request=request
        )

    policy = EgressPolicy(frozenset())
    policy.permit("example.com")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

    with pytest.raises(EgressDenied):
        await TrafilaturaFetcher(policy, http=http).fetch("https://example.com/start")

    await http.aclose()


@pytest.mark.asyncio
async def test_trafilatura_oversize_degrades_to_empty_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 20, request=request)

    policy = EgressPolicy(frozenset())
    policy.permit("example.com")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

    result = await TrafilaturaFetcher(policy, http=http, max_bytes=10).fetch(
        "https://example.com/large"
    )

    assert result.text == ""
    await http.aclose()


@pytest.mark.asyncio
async def test_trafilatura_timeout_degrades_to_empty_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout", request=request)

    policy = EgressPolicy(frozenset())
    policy.permit("example.com")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

    result = await TrafilaturaFetcher(policy, http=http).fetch("https://example.com/timeout")

    assert result.text == ""
    await http.aclose()
