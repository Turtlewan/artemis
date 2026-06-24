"""Document parser port, Docling adapter, and deterministic fake parser."""

from __future__ import annotations

import importlib
import io
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from artemis.ingest.connectors import PageImage, RawItem, document_id_for_source


@dataclass(frozen=True)
class ParsedBlock:
    """A parsed text block with source locator information."""

    text: str
    page: int | None
    bbox: tuple[float, float, float, float] | None
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ParsedDocument:
    """Normalized parsed text, block locators, and page images."""

    text: str
    blocks: Sequence[ParsedBlock]
    page_images: Sequence[PageImage]


class DocumentParser(Protocol):
    """Parser interface from raw connector item to normalized document."""

    def parse(self, item: RawItem) -> ParsedDocument:
        """Parse a raw item."""
        ...


class DoclingParser:
    """Docling-backed parser.

    Docling is an optional dependency and is imported lazily inside ``parse``.
    Text-only web items are handled without Docling.
    """

    def parse(self, item: RawItem) -> ParsedDocument:
        """Parse with Docling when bytes are present, otherwise paragraph text."""
        if item.text is not None and item.raw_bytes is None:
            return _paragraph_document(item.text, page=None, page_images=())

        try:
            import docling  # type: ignore[import-not-found]

            converter_module = importlib.import_module("docling.document_converter")
        except ImportError as exc:
            raise ImportError(
                "DoclingParser requires the optional docling dependency; "
                "install with the docling dependency group on hardware."
            ) from exc

        _docling_version = getattr(docling, "__version__", "unknown")
        _ = _docling_version
        converter_factory = cast(
            Callable[[], object], getattr(converter_module, "DocumentConverter")
        )
        raw_bytes = item.raw_bytes or item.text.encode("utf-8") if item.text is not None else b""
        suffix = _suffix_for_mime(item.mime)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(raw_bytes)
            tmp.flush()
            convert = getattr(converter_factory(), "convert")
            if not callable(convert):
                raise TypeError("Docling DocumentConverter has no callable convert method")
            result = cast(object, convert(Path(tmp.name)))

        doc = getattr(result, "document")
        text = _docling_text(doc)
        blocks = _docling_blocks(doc, text)
        images = _docling_page_images(doc, item.source_id)
        return ParsedDocument(text=text, blocks=blocks, page_images=images)


class FakeParser:
    """Deterministic parser for off-hardware tests."""

    def __init__(self, block_chars: int = 80) -> None:
        self._block_chars = block_chars

    def parse(self, item: RawItem) -> ParsedDocument:
        """Split text into fixed-size synthetic blocks and page images."""
        text = item.text
        if text is None:
            text = (item.raw_bytes or b"").decode("utf-8", errors="replace")
        text = text.strip()
        if not text:
            text = ""

        blocks: list[ParsedBlock] = []
        images: list[PageImage] = []
        document_id = document_id_for_source(item.source_id)
        start = 0
        page = 1
        while start < len(text) or not blocks:
            end = min(len(text), start + self._block_chars)
            block_text = text[start:end]
            blocks.append(
                ParsedBlock(
                    text=block_text,
                    page=page,
                    bbox=(0.0, 0.0, 64.0, 64.0),
                    char_start=start,
                    char_end=end,
                )
            )
            images.append(
                PageImage(
                    document_id=document_id,
                    page=page,
                    image_bytes=f"fake-page-{page}".encode(),
                    width=64,
                    height=64,
                )
            )
            if end >= len(text):
                break
            start = end
            page += 1

        return ParsedDocument(text=text, blocks=blocks, page_images=tuple(images))


def _paragraph_document(
    text: str,
    *,
    page: int | None,
    page_images: Sequence[PageImage],
) -> ParsedDocument:
    blocks: list[ParsedBlock] = []
    cursor = 0
    for paragraph in [p.strip() for p in text.splitlines() if p.strip()]:
        start = text.find(paragraph, cursor)
        if start < 0:
            start = cursor
        end = start + len(paragraph)
        blocks.append(
            ParsedBlock(text=paragraph, page=page, bbox=None, char_start=start, char_end=end)
        )
        cursor = end
    if not blocks:
        blocks.append(
            ParsedBlock(text=text, page=page, bbox=None, char_start=0, char_end=len(text))
        )
    return ParsedDocument(text=text, blocks=blocks, page_images=tuple(page_images))


def _suffix_for_mime(mime: str) -> str:
    if mime == "application/pdf":
        return ".pdf"
    if mime in {"text/html", "application/xhtml+xml"}:
        return ".html"
    if mime == "text/markdown":
        return ".md"
    return ".bin"


def _docling_text(doc: object) -> str:
    export_text = getattr(doc, "export_to_text", None)
    if callable(export_text):
        value = export_text()
        if isinstance(value, str):
            return value
    export_markdown = getattr(doc, "export_to_markdown", None)
    if callable(export_markdown):
        value = export_markdown()
        if isinstance(value, str):
            return value
    return str(doc)


def _docling_blocks(doc: object, text: str) -> Sequence[ParsedBlock]:
    # Conservative fallback for the gated hardware path; real Docling structures
    # vary by version, so parser quality is validated on hardware.
    _ = doc
    return _paragraph_document(text, page=1, page_images=()).blocks


def _docling_page_images(doc: object, source_id: str) -> Sequence[PageImage]:
    document_id = document_id_for_source(source_id)
    images: list[PageImage] = []
    pages = getattr(doc, "pages", None)
    iterable: Iterable[tuple[object, object]]
    if isinstance(pages, dict):
        iterable = pages.items()
    else:
        iterable = enumerate(pages or [], start=1)
    for page_number, page_obj in iterable:
        image_obj = getattr(page_obj, "image", None)
        if image_obj is None:
            continue
        width = int(getattr(image_obj, "width", 0))
        height = int(getattr(image_obj, "height", 0))
        buffer = io.BytesIO()
        save = getattr(image_obj, "save", None)
        if not callable(save):
            continue
        save(buffer, format="PNG")
        images.append(
            PageImage(
                document_id=document_id,
                page=int(page_number),
                image_bytes=buffer.getvalue(),
                width=width,
                height=height,
            )
        )
    return tuple(images)
