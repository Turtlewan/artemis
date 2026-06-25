"""Split-depth Gmail ingestion and quarantined memory extraction."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol

from artemis.config import Settings
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ingest.connectors import Connector, RawItem, Source
from artemis.ingest.pipeline import IngestPipeline
from artemis.memory.write_path import MemoryWriteQueue
from artemis.ports.types import Scope
from artemis.sensitivity import Sensitivity, SensitivityClassifierProtocol
from artemis.untrusted.quarantine import Extract, QuarantinedReader

from .cache import GmailReadCache
from .client import GmailApiPort, extract_body_text, list_attachment_parts

logger = logging.getLogger(__name__)


class MemoryQueuePort(Protocol):
    """Small seam implemented by ``MemoryWriteQueue`` and test fakes."""

    def enqueue(
        self,
        text: str,
        turn_id: str,
        role: str | None = None,
        *,
        source_sensitivity: Sensitivity | None = None,
    ) -> None:
        """Queue sanitized memory text."""
        ...


class QuarantinedReaderPort(Protocol):
    """Small seam implemented by ``QuarantinedReader`` and test fakes."""

    async def read(
        self,
        *,
        raw_content: str,
        source_url: str,
        source_domain: str,
        query: str,
        max_tokens: int = 1024,
    ) -> Extract:
        """Return a privileged-safe extract for raw untrusted content."""
        ...


class GmailBodyConnector:
    """M3 connector for a single Gmail body."""

    def __init__(self, api: GmailApiPort) -> None:
        self._api = api

    def fetch(self, source: Source) -> Iterable[RawItem]:
        """Fetch one message body by id."""
        if source.kind != "email":
            raise ValueError(f"GmailBodyConnector cannot fetch source kind {source.kind!r}")
        msg = self._api.get_message(source.uri, fmt="full")
        yield RawItem(
            raw_bytes=None,
            text=extract_body_text(msg),
            mime="text/plain",
            source_id=f"gmail:{source.uri}",
            origin_uri=f"gmail:{source.uri}",
            fetched_at=datetime.now(UTC),
            page_images=(),
        )


class GmailAttachmentConnector:
    """M3 connector for one Gmail attachment."""

    def __init__(self, api: GmailApiPort) -> None:
        self._api = api

    def fetch(self, source: Source) -> Iterable[RawItem]:
        """Fetch one attachment by encoded source URI."""
        if source.kind != "email_attachment":
            raise ValueError(f"GmailAttachmentConnector cannot fetch source kind {source.kind!r}")
        message_id, attachment_id, mime = source.uri.split(":", 2)
        yield RawItem(
            raw_bytes=self._api.get_attachment(message_id=message_id, attachment_id=attachment_id),
            text=None,
            mime=mime,
            source_id=f"gmail-att:{message_id}:{attachment_id}",
            origin_uri=f"gmail:{message_id}:{attachment_id}",
            fetched_at=datetime.now(UTC),
            page_images=(),
        )


def gmail_connector_for(
    base: Callable[[Source], Connector], api: GmailApiPort
) -> Callable[[Source], Connector]:
    """Wrap an existing connector router with Gmail body/attachment connectors."""

    def connector_for(source: Source) -> Connector:
        if source.kind == "email":
            return GmailBodyConnector(api)
        if source.kind == "email_attachment":
            return GmailAttachmentConnector(api)
        return base(source)

    return connector_for


class GmailIngestor:
    """Apply split-depth ingest for signal bodies and bounded attachments."""

    def __init__(
        self,
        *,
        api: GmailApiPort,
        cache: GmailReadCache,
        pipeline: IngestPipeline,
        settings: Settings,
    ) -> None:
        self._api = api
        self._cache = cache
        self._pipeline = pipeline
        self._settings = settings

    async def ingest_message(self, msg: dict[str, object], *, scope: Scope = OWNER_PRIVATE) -> int:
        """Ingest body and parseable attachments for one signal message."""
        message_id = str(msg.get("id", ""))
        cached = self._cache.get(message_id)
        if cached is not None and cached.body_ingested:
            return 0

        count = 0
        await self._pipeline.ingest(Source(kind="email", uri=message_id, scope=scope))
        count += 1
        max_bytes = self._settings.gmail_attachment_max_mb * 1024 * 1024
        for ref in list_attachment_parts(msg):
            if ref.size > max_bytes or not _parseable_mime(ref.mime):
                continue
            await self._pipeline.ingest(
                Source(
                    kind="email_attachment",
                    uri=f"{message_id}:{ref.attachment_id}:{ref.mime}",
                    scope=scope,
                )
            )
            count += 1
        self._cache.mark_body_ingested(message_id)
        return count


class GmailMemoryExtractor:
    """Quarantine raw mail before enqueueing sanitized memory text.

    Sensitivity is classified once per email on the quarantined Extract summary,
    never raw mail. Classification fails closed to ``"sensitive"``, and the
    memory fact inherits the per-email tag through ``source_sensitivity``.
    """

    def __init__(
        self,
        reader: QuarantinedReader | QuarantinedReaderPort,
        queue: MemoryWriteQueue | MemoryQueuePort,
        classifier: SensitivityClassifierProtocol | None = None,
    ) -> None:
        self._reader = reader
        self._queue = queue
        self._classifier = classifier

    async def extract(self, *, message_id: str, body: str) -> bool:
        """Extract sanitized facts from untrusted body text and enqueue them."""
        extract = await self._reader.read(
            raw_content=body,
            source_url=f"gmail:{message_id}",
            source_domain="gmail",
            query="facts about the owner worth remembering from this email",
        )
        if extract.parse_failed:
            return False
        sensitivity: Sensitivity = "sensitive"
        if self._classifier is not None:
            try:
                sensitivity = await self._classifier.classify(extract.summary)
            except Exception:
                sensitivity = "sensitive"
        logger.debug("Gmail extract %s classified as %s", message_id, sensitivity)
        parts = [extract.summary.strip(), *[claim.strip() for claim in extract.claims]]
        text = "\n".join(part for part in parts if part)
        if not text:
            return False
        self._queue.enqueue(
            text,
            turn_id=f"gmail:{message_id}",
            role="gmail",
            source_sensitivity=sensitivity,
        )
        return True


def _parseable_mime(mime: str) -> bool:
    return mime in {
        "application/pdf",
        "text/plain",
        "text/html",
        "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
