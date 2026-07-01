"""Reach-out web primitives: SSRF-guarded egress, search, and clean-text fetch (ADR-035)."""

from artemis.reachout.egress import EgressDenied, EgressPolicy, registrable_domain
from artemis.reachout.fetch import FetchedContent, Fetcher, TrafilaturaFetcher
from artemis.reachout.search import SearchHit, SearchProvider, TavilySearch
from artemis.reachout.web_tool import ReaderExtract, WebAnswer, WebTool

__all__ = [
    "EgressDenied",
    "EgressPolicy",
    "FetchedContent",
    "Fetcher",
    "ReaderExtract",
    "SearchHit",
    "SearchProvider",
    "TavilySearch",
    "TrafilaturaFetcher",
    "WebAnswer",
    "WebTool",
    "registrable_domain",
]
