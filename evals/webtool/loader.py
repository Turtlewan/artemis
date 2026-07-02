"""Load and verify the frozen web-tool evaluation corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .schema import PageFixture, QueryRecord


def load_corpus(path: Path) -> tuple[list[QueryRecord], dict[str, PageFixture]]:
    """Parse query and page fixture JSON files from a corpus directory."""
    query_dir = path / "queries"
    page_dir = path / "pages"

    queries = [
        QueryRecord.model_validate_json(query_path.read_text(encoding="utf-8"))
        for query_path in sorted(query_dir.glob("*.json"))
    ]
    pages = [
        PageFixture.model_validate_json(page_path.read_text(encoding="utf-8"))
        for page_path in sorted(page_dir.glob("*.json"))
    ]
    return queries, {fixture.id: fixture for fixture in pages}


def verify_integrity(pages: dict[str, PageFixture]) -> None:
    """Raise ValueError if any fixture text does not match its stored SHA-256."""
    for fixture in pages.values():
        actual = hashlib.sha256(fixture.text.encode("utf-8")).hexdigest()
        if actual != fixture.sha256:
            raise ValueError(
                f"page fixture {fixture.id!r} sha256 mismatch: expected {fixture.sha256}, "
                f"got {actual}"
            )
