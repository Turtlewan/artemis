"""Controlled outbound egress for web research adapters."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import tldextract

from artemis.obs import get_logger

logger = get_logger("research.egress")


class EgressDenied(Exception):  # noqa: N818 - spec names this exception without an Error suffix.
    """Raised when an outbound URL is outside the research egress policy."""


def registrable_domain(url: str) -> str:
    """Return the eTLD+1 registrable domain for a URL or host."""

    extracted = tldextract.extract(url)
    return extracted.top_domain_under_public_suffix


def block_private_ip(url: str) -> None:
    """Reject non-HTTPS URLs and hosts resolving to private or reserved addresses."""

    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        logger.warning("egress_blocked", extra={"host": host or ""})
        raise EgressDenied("research egress requires an https URL with a host")

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        logger.warning("egress_blocked", extra={"host": host})
        raise EgressDenied("host resolution failed") from exc

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            logger.warning("egress_blocked", extra={"host": host})
            raise EgressDenied("host resolved to an invalid address") from exc
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_multicast
        ):
            logger.warning("egress_blocked", extra={"host": host})
            raise EgressDenied("host resolved to a blocked address")


class EgressPolicy:
    """Default-deny allowlist for research HTTP.

    ``static_hosts`` are exact API hosts. ``permit`` adds registrable domains
    vouched by search results for the current research cycle. The DR-c engine
    must call ``reset_dynamic`` at the start of each cycle so per-query permits
    do not persist across cycles.
    """

    def __init__(self, static_hosts: frozenset[str]) -> None:
        self._static_hosts = {host.lower() for host in static_hosts}
        self._dynamic_domains: set[str] = set()

    def permit(self, domain: str) -> None:
        """Allow a bare registrable domain for the current research cycle."""

        parsed = urlparse(domain)
        if (
            not domain
            or parsed.scheme
            or parsed.netloc
            or parsed.path != domain
            or parsed.params
            or parsed.query
            or parsed.fragment
            or any(char in domain for char in "/:@[]")
        ):
            raise ValueError("permit expects a bare registrable domain")
        normalized = domain.strip().lower().rstrip(".")
        if normalized != registrable_domain(f"https://{normalized}"):
            raise ValueError("permit expects a bare registrable domain")
        self._dynamic_domains.add(normalized)

    def check(self, url: str) -> None:
        """Raise ``EgressDenied`` unless ``url`` is allowed and publicly routable."""

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        rd = registrable_domain(url)
        if host not in self._static_hosts and rd not in self._dynamic_domains:
            logger.warning("egress_denied", extra={"host": host})
            raise EgressDenied("host is not allowed for research egress")
        block_private_ip(url)

    def reset_dynamic(self) -> None:
        """Clear just-in-time search-result permits."""

        self._dynamic_domains.clear()
