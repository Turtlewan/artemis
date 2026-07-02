"""One-shot capture CLI for creating web-tool page fixtures."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from artemis.reachout.egress import EgressPolicy, registrable_domain
from artemis.reachout.fetch import FetchedContent, TrafilaturaFetcher

from .schema import PageFixture


def _derive_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "page"
    raw = f"{host}{parsed.path}".strip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-").lower()
    return slug or "page"


async def _capture(url: str, out_dir: Path) -> Path:
    egress = EgressPolicy(frozenset({"api.tavily.com"}))
    egress.reset_dynamic()
    egress.permit(registrable_domain(url))
    fetcher = TrafilaturaFetcher(egress)
    try:
        content: FetchedContent = await fetcher.fetch(url)
    finally:
        await fetcher.aclose()

    sha256 = hashlib.sha256(content.text.encode("utf-8")).hexdigest()
    fixture = PageFixture(
        id=_derive_id(url),
        url=url,
        text=content.text,
        sha256=sha256,
        source="captured",
        capture_date=datetime.now(timezone.utc).isoformat(),
        published_date=None,
        injection_subkind=None,
        benign_twin_of=None,
        payload_placement=None,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{fixture.id}.json"
    out_path.write_text(
        json.dumps(fixture.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture one URL as a web-tool page fixture.")
    parser.add_argument("--url", required=True, help="HTTPS URL to capture")
    parser.add_argument("--out", required=True, type=Path, help="Directory for the fixture JSON")
    return parser


def main() -> None:
    """Run the one-shot capture CLI."""
    args = _build_parser().parse_args()
    url = str(args.url)
    out_dir = Path(args.out)
    path = asyncio.run(_capture(url, out_dir))
    print(path)


if __name__ == "__main__":
    main()
