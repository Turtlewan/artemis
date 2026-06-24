"""Ingestion connectors and normalized raw document items."""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import httpx

from artemis.ports.types import Document, Scope


@dataclass(frozen=True)
class Source:
    """A source URI to ingest into a scope."""

    kind: Literal["file", "web", "email", "email_attachment", "calendar_meeting"]
    uri: str
    scope: Scope


@dataclass(frozen=True)
class PageImage:
    """Rendered page image shared by ingest and visual indexing."""

    document_id: str
    page: int
    image_bytes: bytes
    width: int
    height: int


@dataclass(frozen=True)
class RawItem:
    """Raw item fetched from a connector before parser normalization."""

    raw_bytes: bytes | None
    text: str | None
    mime: str
    source_id: str
    origin_uri: str
    fetched_at: datetime
    page_images: Sequence[PageImage] = field(default_factory=tuple)


class Connector(Protocol):
    """Fetch one or more raw items from a source."""

    def fetch(self, source: Source) -> Iterable[RawItem]:
        """Return raw items for ``source``."""
        ...


class FileConnector:
    """Local file connector constrained to configured roots."""

    def __init__(self, allowed_roots: Sequence[Path]) -> None:
        if not allowed_roots:
            raise ValueError("FileConnector requires at least one allowed root")
        self._allowed_roots = tuple(root.resolve() for root in allowed_roots)

    def fetch(self, source: Source) -> Iterable[RawItem]:
        """Read a single allowed local file."""
        if source.kind != "file":
            raise ValueError(f"FileConnector cannot fetch source kind {source.kind!r}")
        path = Path(source.uri).expanduser().resolve()
        if not self._is_allowed(path):
            raise ValueError(f"FileConnector: path outside allowed roots: {source.uri!r}")
        if not path.is_file():
            raise FileNotFoundError(path)

        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        yield RawItem(
            raw_bytes=path.read_bytes(),
            text=None,
            mime=mime,
            source_id=str(path),
            origin_uri=str(path),
            fetched_at=datetime.now(UTC),
            page_images=(),
        )

    def _is_allowed(self, path: Path) -> bool:
        return any(path == root or path.is_relative_to(root) for root in self._allowed_roots)


class WebConnector:
    """HTTP(S) connector using trafilatura extraction behind a fetch seam."""

    def fetch(self, source: Source) -> Iterable[RawItem]:
        """Fetch and clean one web page."""
        if source.kind != "web":
            raise ValueError(f"WebConnector cannot fetch source kind {source.kind!r}")
        if not (source.uri.startswith("http://") or source.uri.startswith("https://")):
            raise ValueError("WebConnector: disallowed scheme in URI")

        import trafilatura

        html = self._fetch_url(source.uri)
        text = trafilatura.extract(html, url=source.uri) or html
        yield RawItem(
            raw_bytes=None,
            text=text,
            mime="text/html",
            source_id=source.uri,
            origin_uri=source.uri,
            fetched_at=datetime.now(UTC),
            page_images=(),
        )

    def _fetch_url(self, url: str) -> str:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return response.text


def document_id_for_source(source_id: str) -> str:
    """Return the stable document id for a source id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, source_id))


def content_hash_for(source_id: str, parsed_text: str) -> str:
    """Return the idempotency hash for normalized text and source id."""
    h = hashlib.sha256()
    h.update(source_id.encode("utf-8"))
    h.update(b"\0")
    h.update(parsed_text.encode("utf-8"))
    return h.hexdigest()


def to_document(item: RawItem, scope: Scope, parsed_text: str) -> Document:
    """Build the port ``Document`` from a parsed raw item."""
    return Document(
        document_id=document_id_for_source(item.source_id),
        source_id=item.source_id,
        content_hash=content_hash_for(item.source_id, parsed_text),
        scope=scope,
        text=parsed_text,
    )
