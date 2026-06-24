"""Bounded Gmail backfill and History API incremental sync."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from artemis.config import Settings
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ports.types import Scope

from .cache import CachedMessage, GmailReadCache
from .client import (
    GmailApiPort,
    categorize,
    extract_body_text,
    extract_headers,
    is_signal,
    list_attachment_parts,
)
from .ingest import GmailIngestor, GmailMemoryExtractor


class SyncNotInitialisedError(Exception):
    """Raised when incremental sync runs before a backfill cursor exists."""


class HistoryExpiredError(Exception):
    """Raised when Gmail reports the stored history cursor is too old."""


@dataclass(frozen=True)
class BackfillResult:
    """Backfill counters."""

    scanned: int
    signal_ingested: int


@dataclass(frozen=True)
class IncrementalResult:
    """Incremental sync counters."""

    added: int
    removed: int
    label_changes: int


class GmailSync:
    """Synchronise Gmail metadata for all mail and full content for signal mail."""

    def __init__(
        self,
        api: GmailApiPort,
        cache: GmailReadCache,
        ingestor: GmailIngestor,
        memory: GmailMemoryExtractor,
        settings: Settings,
        *,
        scope: Scope = OWNER_PRIVATE,
    ) -> None:
        self._api = api
        self._cache = cache
        self._ingestor = ingestor
        self._memory = memory
        self._settings = settings
        self._scope = scope

    async def backfill(self) -> BackfillResult:
        """Backfill the bounded window and seed the pre-captured cursor."""
        cursor_id = self._api.current_history_id()
        after = datetime.now(UTC).date() - timedelta(days=30 * self._settings.gmail_backfill_months)
        q = f"after:{after:%Y/%m/%d}"
        scanned = 0
        signal_ingested = 0
        page_token: str | None = None
        while True:
            ids, page_token = self._api.list_message_ids(q=q, page_token=page_token)
            for message_id in ids:
                meta = self._api.get_message(message_id, fmt="metadata")
                cached = self._preserve_ingested(self._to_cached(meta))
                self._cache.upsert(cached)
                scanned += 1
                if is_signal(cached.category):
                    full = self._api.get_message(message_id, fmt="full")
                    ingested = await self._ingestor.ingest_message(
                        _dict_message(full), scope=self._scope
                    )
                    if ingested:
                        signal_ingested += 1
                        await self._memory.extract(
                            message_id=message_id, body=extract_body_text(full)
                        )
            if page_token is None:
                break
        self._cache.set_cursor(cursor_id)
        return BackfillResult(scanned=scanned, signal_ingested=signal_ingested)

    async def incremental(self) -> IncrementalResult:
        """Apply History API deltas and advance to the response-level cursor."""
        start = self._cache.get_cursor()
        if start is None:
            raise SyncNotInitialisedError("run backfill first")
        added = 0
        removed = 0
        label_changes = 0
        latest_history_id = ""
        page_token: str | None = None
        while True:
            try:
                records, page_token, response_history_id = self._api.list_history(
                    start_history_id=start, page_token=page_token
                )
            except Exception as exc:
                if "404" in str(exc):
                    raise HistoryExpiredError("cursor too old; re-backfill") from exc
                raise
            if response_history_id:
                latest_history_id = response_history_id
            for record in records:
                for item in _history_messages(record.get("messagesAdded")):
                    message_id = _history_message_id(item)
                    if not message_id:
                        continue
                    await self._upsert_and_maybe_ingest(message_id)
                    added += 1
                for item in _history_messages(record.get("messagesDeleted")):
                    message_id = _history_message_id(item)
                    if not message_id:
                        continue
                    self._cache.mark_removed(message_id)
                    removed += 1
                for key in ("labelsAdded", "labelsRemoved"):
                    for item in _history_messages(record.get(key)):
                        message_id = _history_message_id(item)
                        if not message_id:
                            continue
                        meta = self._api.get_message(message_id, fmt="metadata")
                        self._cache.upsert(self._preserve_ingested(self._to_cached(meta)))
                        label_changes += 1
            if page_token is None:
                break
        if latest_history_id:
            self._cache.set_cursor(latest_history_id)
        return IncrementalResult(added=added, removed=removed, label_changes=label_changes)

    def _to_cached(self, msg: Mapping[str, object]) -> CachedMessage:
        """Convert a Gmail metadata response into the cache row."""
        headers = extract_headers(msg)
        labels = _str_tuple(msg.get("labelIds"))
        category = categorize(labels)
        return CachedMessage(
            message_id=str(msg.get("id", "")),
            thread_id=str(msg.get("threadId", "")),
            history_id=str(msg.get("historyId", "")),
            sender=headers.get("from", ""),
            subject=headers.get("subject", ""),
            internal_date_ms=_int_value(msg.get("internalDate")),
            category=category,
            snippet=str(msg.get("snippet", "")),
            label_ids=labels,
            has_attachments=bool(list_attachment_parts(msg)),
            unread="UNREAD" in labels,
            important="IMPORTANT" in labels,
            body_ingested=False,
        )

    async def _upsert_and_maybe_ingest(self, message_id: str) -> None:
        meta = self._api.get_message(message_id, fmt="metadata")
        cached = self._preserve_ingested(self._to_cached(meta))
        self._cache.upsert(cached)
        if is_signal(cached.category):
            full = self._api.get_message(message_id, fmt="full")
            ingested = await self._ingestor.ingest_message(_dict_message(full), scope=self._scope)
            if ingested:
                await self._memory.extract(message_id=message_id, body=extract_body_text(full))

    def _preserve_ingested(self, msg: CachedMessage) -> CachedMessage:
        existing = self._cache.get(msg.message_id)
        if existing is None or not existing.body_ingested:
            return msg
        return replace(msg, body_ingested=True)


def _dict_message(msg: Mapping[str, object]) -> dict[str, object]:
    return dict(msg)


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return ()


def _int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _history_messages(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _history_message_id(item: Mapping[str, object]) -> str:
    message = item.get("message")
    if not isinstance(message, Mapping):
        return ""
    value = message.get("id")
    return value if isinstance(value, str) else ""
