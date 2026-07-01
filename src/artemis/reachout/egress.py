"""Controlled outbound egress for reach-out web adapters (ADR-035 decision 2)."""

from __future__ import annotations
import ipaddress
import logging
import socket
from urllib.parse import urlparse
import tldextract

_log = logging.getLogger(__name__)
_MAX_DYNAMIC = 64  # hard cap so a missed reset_dynamic() cannot grow egress unboundedly


class EgressDenied(Exception):  # noqa: N818 — named without an Error suffix by design
    """Raised when an outbound URL is outside the egress policy."""


def registrable_domain(url: str) -> str:
    """Return the eTLD+1 registrable domain for a URL or host."""
    return tldextract.extract(url).top_domain_under_public_suffix


def _validated_ip(host: str) -> ipaddress._BaseAddress:
    """Resolve host, reject any non-public address, return the ONE address to pin.

    Covers IPv4 + IPv6, incl. IPv4-mapped IPv6 (::ffff:127.0.0.1) via .ipv4_mapped
    unwrap before the range test."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise EgressDenied("host resolution failed") from exc
    chosen: ipaddress._BaseAddress | None = None
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError as exc:
            raise EgressDenied("host resolved to an invalid address") from exc
        probe = ip
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            probe = mapped  # unwrap ::ffff:a.b.c.d before range checks
        if (
            probe.is_private
            or probe.is_loopback
            or probe.is_link_local
            or probe.is_reserved
            or probe.is_unspecified
            or probe.is_multicast
        ):
            _log.warning("egress_blocked host=%s addr=%s", host, ip)
            raise EgressDenied("host resolved to a blocked address")
        chosen = chosen or ip
    if chosen is None:
        raise EgressDenied("host did not resolve")
    return chosen


def block_private_ip(url: str) -> None:
    """Reject non-HTTPS URLs and hosts resolving to private/reserved addresses (allowlist-agnostic)."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        _log.warning("egress_blocked host=%s", host or "")
        raise EgressDenied("egress requires an https URL with a host")
    _validated_ip(host)


class EgressPolicy:
    """Default-deny allowlist. Static hosts are exact API hosts; `permit` adds
    registrable domains vouched for the current cycle. Callers MUST `reset_dynamic`
    at the start of each cycle so per-query permits do not persist; a hard cap
    (`_MAX_DYNAMIC`) bounds the set even if a reset is missed."""

    def __init__(self, static_hosts: frozenset[str]) -> None:
        # static entries are exact "host" or "host:port"; a bare host implies :443 only
        self._static_hosts = {h.lower() for h in static_hosts}
        self._dynamic_domains: set[str] = set()

    def permit(self, domain: str) -> None:
        """Vouch for a bare registrable domain for the current cycle (capped, see `_MAX_DYNAMIC`)."""
        parsed = urlparse(domain)
        if (
            not domain
            or parsed.scheme
            or parsed.netloc
            or parsed.path != domain
            or parsed.params
            or parsed.query
            or parsed.fragment
            or any(c in domain for c in "/:@[]")
        ):
            raise ValueError("permit expects a bare registrable domain")
        normalized = domain.strip().lower().rstrip(".")
        if normalized != registrable_domain(f"https://{normalized}"):
            raise ValueError("permit expects a bare registrable domain")
        if normalized not in self._dynamic_domains and len(self._dynamic_domains) >= _MAX_DYNAMIC:
            _log.warning("egress_permit_capped size=%d", len(self._dynamic_domains))
            raise EgressDenied("dynamic egress set is full — reset_dynamic() was not called")
        self._dynamic_domains.add(normalized)

    def _check_allow_and_port(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port  # None when absent
        rd = registrable_domain(url)
        host_port = f"{host}:{port}" if port is not None else host
        # dynamic (search-vouched) domains are 443-only; a non-443 port must be an
        # explicit host:port in the static allowlist.
        if port not in (None, 443):
            if host_port not in self._static_hosts:
                _log.warning("egress_denied host=%s port=%s", host, port)
                raise EgressDenied("non-443 port is not explicitly allowlisted")
            return
        if host in self._static_hosts or host_port in self._static_hosts:
            return
        if rd in self._dynamic_domains:
            return
        _log.warning("egress_denied host=%s", host)
        raise EgressDenied("host is not allowed for egress")

    def check(self, url: str) -> None:
        """Allowlist + port-lock + SSRF, discarding the pinned IP (search path)."""
        self._check_allow_and_port(url)
        block_private_ip(url)

    def pin(self, url: str) -> str:
        """Allowlist + port-lock + SSRF; return the validated IP string to CONNECT to.

        DNS-rebinding TOCTOU: the caller must connect to this exact address while keeping
        Host header + TLS SNI = the original hostname, so the connect-time socket cannot be
        re-resolved to a private/metadata IP after validation."""
        self._check_allow_and_port(url)
        parsed = urlparse(url)
        host = parsed.hostname
        # https-only, same invariant check() enforces via block_private_ip — pin() is the ONLY
        # egress gate the fetcher runs on the initial URL, so a missing scheme check here would
        # let fetch("http://allowlisted/…") connect over plaintext.
        if parsed.scheme != "https" or not host:
            _log.warning("egress_blocked host=%s", host or "")
            raise EgressDenied("egress requires an https URL with a host")
        return str(_validated_ip(host))

    def reset_dynamic(self) -> None:
        """Clear all `permit`-ed domains; callers should call this at the start of each cycle."""
        self._dynamic_domains.clear()
