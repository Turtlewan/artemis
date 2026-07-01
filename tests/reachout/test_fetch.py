from __future__ import annotations

from collections.abc import Callable, Mapping
import socket

import httpx
import pytest
import trafilatura

from artemis.reachout.egress import EgressDenied, EgressPolicy
from artemis.reachout.fetch import FetchedContent, TrafilaturaFetcher, _PinnedTransport

SockAddr = tuple[str, int] | tuple[str, int, int, int]
AddrInfo = tuple[socket.AddressFamily, socket.SocketKind, int, str, SockAddr]
GetAddrInfo = Callable[[str, object], list[AddrInfo]]
Handler = Callable[[httpx.Request], httpx.Response]


def fake_gai_by_host(host_to_ip: Mapping[str, str]) -> GetAddrInfo:
    def _gai(host: str, port: object, *args: object, **kwargs: object) -> list[AddrInfo]:
        ip = host_to_ip[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _gai


def fake_gai(ip: str) -> GetAddrInfo:
    return fake_gai_by_host({"example.com": ip})


def pinned_client(egress: EgressPolicy, handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=_PinnedTransport(egress, httpx.MockTransport(handler)),
        follow_redirects=False,
    )


def article_html() -> str:
    paragraph = "This article explains pinned transports and guarded web fetching. " * 20
    paragraphs = "".join(f"<p>{paragraph}</p>" for _ in range(4))
    return f"<html><body><article><h1>Title</h1>{paragraphs}</article></body></html>"


async def test_fetch_connects_to_pinned_ip_preserving_host_and_sni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["Host"] == "example.com"
        assert request.extensions.get("sni_hostname") == "example.com"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=article_html().encode(),
        )

    egress = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))
    http = pinned_client(egress, handler)
    fetcher = TrafilaturaFetcher(egress, http=http)
    try:
        result = await fetcher.fetch("https://example.com/article", max_chars=10)
    finally:
        await http.aclose()

    assert isinstance(result, FetchedContent)
    assert result.domain == "example.com"
    assert result.text != ""
    assert len(result.text) <= 10


async def test_fetch_rejects_auto_following_injected_client() -> None:
    egress = EgressPolicy(frozenset({"example.com"}))
    http = httpx.AsyncClient(follow_redirects=True)
    try:
        with pytest.raises(ValueError):
            TrafilaturaFetcher(egress, http=http)
    finally:
        await http.aclose()


async def test_fetch_degrades_non_html_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extract_called = False

    def extract(*args: object, **kwargs: object) -> str:
        nonlocal extract_called
        extract_called = True
        return "should not be used"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.7",
        )

    egress = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))
    monkeypatch.setattr(trafilatura, "extract", extract)
    http = pinned_client(egress, handler)
    fetcher = TrafilaturaFetcher(egress, http=http)
    try:
        result = await fetcher.fetch("https://example.com/file.pdf")
    finally:
        await http.aclose()

    assert result.text == ""
    assert not extract_called


async def test_fetch_degrades_oversize_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body>too long</body></html>",
        )

    egress = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))
    http = pinned_client(egress, handler)
    fetcher = TrafilaturaFetcher(egress, http=http, max_bytes=10)
    try:
        result = await fetcher.fetch("https://example.com/large")
    finally:
        await http.aclose()

    assert result.text == ""


async def test_fetch_redirect_to_internal_host_raises_egress_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        return httpx.Response(302, headers={"location": "https://internal.example.com/"})

    egress = EgressPolicy(frozenset())
    egress.permit("example.com")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        fake_gai_by_host(
            {
                "example.com": "93.184.216.34",
                "internal.example.com": "127.0.0.1",
            }
        ),
    )
    http = pinned_client(egress, handler)
    fetcher = TrafilaturaFetcher(egress, http=http)
    try:
        with pytest.raises(EgressDenied):
            await fetcher.fetch("https://example.com/redirect")
    finally:
        await http.aclose()


async def test_fetch_degrades_extraction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def extract(*args: object, **kwargs: object) -> str:
        raise RuntimeError("extract failed")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=article_html().encode(),
        )

    egress = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))
    monkeypatch.setattr(trafilatura, "extract", extract)
    http = pinned_client(egress, handler)
    fetcher = TrafilaturaFetcher(egress, http=http)
    try:
        result = await fetcher.fetch("https://example.com/article")
    finally:
        await http.aclose()

    assert result.domain == "example.com"
    assert result.text == ""


async def test_fetch_rejects_plaintext_http_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # BLOCK: pin() must reject http:// so the fetcher never opens a plaintext connection, even to
    # an allowlisted host. EgressDenied propagates past the boundary (not degraded-to-empty).
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not be reached
        raise AssertionError("plaintext request must never reach the transport inner")

    egress = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))
    http = pinned_client(egress, handler)
    fetcher = TrafilaturaFetcher(egress, http=http)
    try:
        with pytest.raises(EgressDenied):
            await fetcher.fetch("http://example.com/article")
    finally:
        await http.aclose()


async def test_fetch_pins_public_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    public_v6 = "2606:2800:220:1:248:1893:25c8:1946"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == public_v6
        assert request.headers["Host"] == "example.com"
        assert request.extensions.get("sni_hostname") == "example.com"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=article_html().encode(),
        )

    egress = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai(public_v6))
    http = pinned_client(egress, handler)
    fetcher = TrafilaturaFetcher(egress, http=http)
    try:
        result = await fetcher.fetch("https://example.com/article")
    finally:
        await http.aclose()

    assert result.text != ""
    assert result.domain == "example.com"
