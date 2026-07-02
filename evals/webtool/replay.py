"""Replay search and fetch adapters for the frozen web-tool corpus."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from urllib.parse import urlparse

from artemis.reachout.egress import registrable_domain
from artemis.reachout.fetch import FetchedContent
from artemis.reachout.search import SearchHit

from .schema import PageFixture, QueryRecord


class ReplaySearch:
    """Search adapter that returns the corpus pages associated with an exact query."""

    def __init__(
        self,
        records: Sequence[QueryRecord],
        fixtures: Mapping[str, PageFixture],
    ) -> None:
        self._records = {record.query: record for record in records}
        self._fixtures = dict(fixtures)
        self._replay_urls = {
            fixture.id: _egress_safe_url(fixture) for fixture in self._fixtures.values()
        }
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, count: int = 8) -> list[SearchHit]:
        """Return frozen hits for ``query`` without network access."""
        self.calls.append((query, count))
        record = self._records.get(query)
        if record is None:
            return []

        hits: list[SearchHit] = []
        for page_ref in record.pages[:count]:
            fixture = self._fixtures[page_ref.fixture_id]
            hits.append(
                SearchHit(
                    title=fixture.id,
                    url=self._replay_urls[fixture.id],
                    snippet=fixture.text[:240],
                )
            )
        return hits

    def url_for_fixture(self, fixture_id: str) -> str:
        """Return the egress-safe replay URL used for a fixture."""
        return self._replay_urls[fixture_id]


class ReplayFetcher:
    """Fetcher adapter that serves clean text from frozen page fixtures."""

    def __init__(self, fixtures: Mapping[str, PageFixture]) -> None:
        self._by_url: dict[str, PageFixture] = {}
        self._original_by_replay: dict[str, str] = {}
        for fixture in fixtures.values():
            replay_url = _egress_safe_url(fixture)
            self._by_url[fixture.url] = fixture
            self._by_url[replay_url] = fixture
            self._original_by_replay[replay_url] = fixture.url
        self.calls: list[str] = []

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        """Return frozen clean text for ``url`` without network access."""
        self.calls.append(url)
        fixture = self._by_url[url]
        return FetchedContent(
            url=fixture.url,
            domain=registrable_domain(fixture.url),
            text=fixture.text[:max_chars],
        )

    def original_url(self, replay_url: str) -> str:
        """Map an egress-safe replay URL back to the fixture's original URL."""
        return self._original_by_replay.get(replay_url, replay_url)


def _egress_safe_url(fixture: PageFixture) -> str:
    if registrable_domain(fixture.url):
        return fixture.url
    parsed = urlparse(fixture.url)
    host = parsed.hostname or fixture.id
    safe_host = re.sub(r"[^a-z0-9-]+", "-", host.lower()).strip("-") or "fixture"
    path = parsed.path or f"/{fixture.id}"
    return f"https://{safe_host}.replay.example.com{path}"
