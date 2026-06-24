"""Web research ports and adapters."""

from artemis.research.egress import EgressDenied, EgressPolicy, registrable_domain
from artemis.research.fetch import (
    FetchedContent,
    Fetcher,
    JinaFetcher,
    PlaywrightFetcher,
    TrafilaturaFetcher,
)
from artemis.research.search import (
    BraveSearch,
    SearchError,
    SearchHit,
    SearchProvider,
    TavilySearch,
)

__all__ = [
    "BraveSearch",
    "EgressDenied",
    "EgressPolicy",
    "FetchedContent",
    "Fetcher",
    "JinaFetcher",
    "PlaywrightFetcher",
    "SearchError",
    "SearchHit",
    "SearchProvider",
    "TavilySearch",
    "TrafilaturaFetcher",
    "registrable_domain",
]
