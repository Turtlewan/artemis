from __future__ import annotations

from collections.abc import Callable
import socket

import pytest

from artemis.reachout import egress
from artemis.reachout.egress import EgressDenied, EgressPolicy, registrable_domain

SockAddr = tuple[str, int] | tuple[str, int, int, int]
AddrInfo = tuple[socket.AddressFamily, socket.SocketKind, int, str, SockAddr]
GetAddrInfo = Callable[[str, object], list[AddrInfo]]


def fake_gai(ip: str, family: socket.AddressFamily = socket.AF_INET) -> GetAddrInfo:
    def _gai(host: str, port: object, *args: object, **kwargs: object) -> list[AddrInfo]:
        if family == socket.AF_INET6:
            return [(family, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _gai


def echo_literal_gai(family: socket.AddressFamily = socket.AF_INET) -> GetAddrInfo:
    def _gai(host: str, port: object, *args: object, **kwargs: object) -> list[AddrInfo]:
        if ":" in host:
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (host, 0, 0, 0))]
        return [(family, socket.SOCK_STREAM, 6, "", (host, 0))]

    return _gai


def test_registrable_domain_returns_etld_plus_one() -> None:
    assert registrable_domain("https://www.example.co.uk/x") == "example.co.uk"
    assert registrable_domain("https://a.b.example.com/") == "example.com"


def test_non_https_is_denied() -> None:
    policy = EgressPolicy(frozenset({"example.com"}))

    with pytest.raises(EgressDenied):
        policy.check("http://example.com")


def test_non_allowlisted_host_is_denied() -> None:
    policy = EgressPolicy(frozenset({"example.com"}))

    with pytest.raises(EgressDenied):
        policy.check("https://evil.test")


@pytest.mark.parametrize(
    ("ip", "family"),
    [
        ("127.0.0.1", socket.AF_INET),
        ("169.254.169.254", socket.AF_INET),
        ("10.0.0.5", socket.AF_INET),
        ("::1", socket.AF_INET6),
    ],
)
def test_bad_ips_behind_permitted_host_are_denied(
    monkeypatch: pytest.MonkeyPatch,
    ip: str,
    family: socket.AddressFamily,
) -> None:
    policy = EgressPolicy(frozenset())
    policy.permit("example.com")
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai(ip, family))

    with pytest.raises(EgressDenied):
        policy.check("https://example.com/")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1",
        "https://[::1]",
        "https://169.254.169.254",
    ],
)
def test_literal_ip_urls_are_denied(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    policy = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", echo_literal_gai())

    with pytest.raises(EgressDenied):
        policy.check(url)


@pytest.mark.parametrize(
    "ip",
    [
        "::ffff:169.254.169.254",
        "::ffff:127.0.0.1",
    ],
)
def test_ipv4_mapped_ipv6_behind_permitted_host_is_denied(
    monkeypatch: pytest.MonkeyPatch,
    ip: str,
) -> None:
    policy = EgressPolicy(frozenset())
    policy.permit("example.com")
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai(ip, socket.AF_INET6))

    with pytest.raises(EgressDenied):
        policy.check("https://example.com/")


def test_literal_ipv4_mapped_ipv6_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", echo_literal_gai(socket.AF_INET6))

    with pytest.raises(EgressDenied):
        policy.check("https://[::ffff:127.0.0.1]")


def test_static_public_host_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))

    policy.check("https://example.com/")


def test_dynamic_domain_is_locked_to_443(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = EgressPolicy(frozenset())
    policy.permit("example.com")
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))

    with pytest.raises(EgressDenied):
        policy.check("https://example.com:8500/")


def test_static_host_port_allows_non_443(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = EgressPolicy(frozenset({"example.com:8500"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))

    policy.check("https://example.com:8500/")


def test_pin_returns_validated_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = EgressPolicy(frozenset())
    policy.permit("example.com")
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))

    assert policy.pin("https://example.com/") == "93.184.216.34"


def test_permit_matches_registrable_domain_and_reset_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = EgressPolicy(frozenset())
    policy.permit("example.org")
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))

    policy.check("https://www.example.org/")

    policy.reset_dynamic()

    with pytest.raises(EgressDenied):
        policy.check("https://www.example.org/")


def test_dynamic_permit_cap_raises_without_reset() -> None:
    policy = EgressPolicy(frozenset())

    for index in range(egress._MAX_DYNAMIC):
        policy.permit(f"example{index}.com")

    with pytest.raises(EgressDenied):
        policy.permit(f"example{egress._MAX_DYNAMIC}.com")


def test_pin_rejects_non_https(monkeypatch: pytest.MonkeyPatch) -> None:
    # pin() is the ONLY egress gate the fetcher runs on the initial URL, so it must enforce
    # https-only just like check() does — else fetch("http://…") would connect over plaintext.
    policy = EgressPolicy(frozenset({"example.com"}))
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai("93.184.216.34"))

    with pytest.raises(EgressDenied):
        policy.pin("http://example.com/")


def test_pin_captures_first_resolution_not_a_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    # DNS-rebinding sim: getaddrinfo would return a public IP first, then loopback. pin() resolves
    # exactly once and returns the public IP it validated — a later re-resolution is never consulted.
    policy = EgressPolicy(frozenset({"example.com"}))
    calls = {"n": 0}

    def rebinding_gai(host: str, port: object, *args: object, **kwargs: object) -> list[AddrInfo]:
        calls["n"] += 1
        ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_gai)

    assert policy.pin("https://example.com/") == "93.184.216.34"
    assert calls["n"] == 1


def test_pin_accepts_public_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = EgressPolicy(frozenset({"example.com"}))
    public_v6 = "2606:2800:220:1:248:1893:25c8:1946"
    monkeypatch.setattr(socket, "getaddrinfo", fake_gai(public_v6, socket.AF_INET6))

    assert policy.pin("https://example.com/") == public_v6
