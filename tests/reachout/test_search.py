from __future__ import annotations

from collections.abc import Callable
import json
import socket

import httpx
import pytest

from artemis.reachout.egress import EgressDenied, EgressPolicy
from artemis.reachout.search import SearchError, SearchHit, TavilySearch

SockAddr = tuple[str, int] | tuple[str, int, int, int]
AddrInfo = tuple[socket.AddressFamily, socket.SocketKind, int, str, SockAddr]
GetAddrInfo = Callable[[str, object], list[AddrInfo]]


def fake_gai(ip: str, family: socket.AddressFamily = socket.AF_INET) -> GetAddrInfo:
    def _gai(host: str, port: object, *args: object, **kwargs: object) -> list[AddrInfo]:
        if family == socket.AF_INET6:
            return [(family, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _gai


async def test_tavily_search_maps_results_and_redacts_body_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "T1",
                        "url": "https://a.example.com/1",
                        "content": "snippet one",
                    },
                    {
                        "title": "T2",
                        "url": "https://b.example.com/2",
                        "content": "snippet two",
                    },
                ]
            },
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        event_hooks={"request": [TavilySearch._redact_secrets_for_hooks]},
    )
    search = TavilySearch("SECRET-KEY-123", EgressPolicy(frozenset({"api.tavily.com"})), http=http)
    try:
        result = await search.search("query", count=2)
    finally:
        await http.aclose()

    assert len(result) == 2
    assert all(isinstance(hit, SearchHit) for hit in result)
    assert result[0].snippet == "snippet one"
    assert captured
    real_body = json.loads(captured[0].content)
    assert real_body["api_key"] == "SECRET-KEY-123"
    snapshot = captured[0].extensions["artemis_safe_snapshot"]
    assert "SECRET-KEY-123" not in json.dumps(snapshot)


async def test_tavily_search_non_success_raises_search_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        event_hooks={"request": [TavilySearch._redact_secrets_for_hooks]},
    )
    search = TavilySearch("SECRET-KEY-123", EgressPolicy(frozenset({"api.tavily.com"})), http=http)
    try:
        with pytest.raises(SearchError):
            await search.search("query")
    finally:
        await http.aclose()


async def test_tavily_search_enforces_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        event_hooks={"request": [TavilySearch._redact_secrets_for_hooks]},
    )
    search = TavilySearch(
        "SECRET-KEY-123",
        EgressPolicy(frozenset({"api.tavily.com"})),
        base_url="https://not-allowed.example.com/search",
        http=http,
    )
    try:
        with pytest.raises(EgressDenied):
            await search.search("query")
    finally:
        await http.aclose()
