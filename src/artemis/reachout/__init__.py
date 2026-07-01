"""Reach-out web primitives: SSRF-guarded egress, search, and clean-text fetch (ADR-035)."""

from artemis.reachout.egress import EgressDenied, EgressPolicy, registrable_domain
from artemis.reachout.fetch import FetchedContent, Fetcher, TrafilaturaFetcher
from artemis.reachout.search import SearchHit, SearchProvider, TavilySearch

__all__ = [
    "EgressDenied",
    "EgressPolicy",
    "FetchedContent",
    "Fetcher",
    "SearchHit",
    "SearchProvider",
    "TavilySearch",
    "TrafilaturaFetcher",
    "registrable_domain",
]
