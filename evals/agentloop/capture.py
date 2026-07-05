"""One-shot capture CLI for creating agent-loop record fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from artemis.data.store import DataStore, Record

from .schema import RecordFixture


def capture_records(store: DataStore, *, domain: str, out_dir: Path) -> list[Path]:
    """Capture one domain from a DataStore as redacted RecordFixture JSON files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for record in store.query(domain=domain, limit=10_000):
        fixture = _record_fixture(record)
        out_path = out_dir / f"{_slug(record.domain)}-{_slug(record.kind)}-{_slug(record.key)}.json"
        out_path.write_text(
            json.dumps(fixture.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths.append(out_path)
    return paths


def _record_fixture(record: Record) -> RecordFixture:
    return RecordFixture(
        domain=record.domain,
        kind=record.kind,
        key=record.key,
        sanitized_text=record.sanitized_text,
        payload=_redact_payload(record.payload),
        source=record.source,
        fetched_at=record.fetched_at,
        sha256=hashlib.sha256(record.sanitized_text.encode("utf-8")).hexdigest(),
    )


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(value) for key, value in payload.items()}


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    serialized = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:8]
    return f"[redacted:{digest}]"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "record"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture DataStore records as agent-loop fixtures."
    )
    parser.add_argument("--domain", required=True, help="Domain label to query")
    parser.add_argument("--data-dir", required=True, type=Path, help="Artemis data directory")
    parser.add_argument("--out", required=True, type=Path, help="Directory for fixture JSON files")
    return parser


def main() -> None:
    """Run the one-shot capture CLI."""
    args = _build_parser().parse_args()
    data_dir = Path(args.data_dir)
    db_path = data_dir if data_dir.is_file() else data_dir / "spine.db"
    store = DataStore(str(db_path))
    try:
        paths = capture_records(store, domain=str(args.domain), out_dir=Path(args.out))
    finally:
        store.close()
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
