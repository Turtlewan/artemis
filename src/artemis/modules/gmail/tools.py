"""Read-only Gmail tools with spotlighted body returns."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel, Field

from artemis.manifest import ActionRisk, ToolSpec
from artemis.untrusted.spotlight import spotlight

from .cache import CachedMessage, GmailReadCache
from .client import (
    GmailApiPort,
    MailCategory,
    categorize,
    extract_body_text,
    extract_headers,
    list_attachment_parts,
)


class GmailSearchArgs(BaseModel):
    """Arguments for Gmail search."""

    query: str
    max_results: int = Field(default=20, ge=1, le=100)


class GetMessageArgs(BaseModel):
    """Arguments for reading one message."""

    message_id: str


class ListThreadsArgs(BaseModel):
    """Arguments for listing Gmail threads."""

    query: str = ""
    max_results: int = Field(default=20, ge=1, le=100)


class GetThreadArgs(BaseModel):
    """Arguments for reading one Gmail thread."""

    thread_id: str


class ListUnreadArgs(BaseModel):
    """Arguments for unread metadata."""

    category: str | None = None


class MessageRef(BaseModel):
    """Metadata-only message reference; snippets are intentionally omitted."""

    message_id: str
    thread_id: str
    sender: str
    subject: str
    date_iso: str
    category: str
    unread: bool


class GmailSearchResult(BaseModel):
    """List of Gmail message references."""

    messages: list[MessageRef]


class MessageDetail(BaseModel):
    """Full message detail with body marked as untrusted."""

    header: dict[str, str]
    body_spotlighted: str
    category: str
    has_attachments: bool


class ThreadRef(BaseModel):
    """Thread reference."""

    thread_id: str


class ThreadList(BaseModel):
    """Thread list result."""

    threads: list[ThreadRef]


class ThreadDetail(BaseModel):
    """Thread messages with spotlighted bodies."""

    messages: list[MessageDetail]


def build_gmail_tools(api: GmailApiPort, cache: GmailReadCache) -> list[ToolSpec]:
    """Build five async read ToolSpecs with injected Gmail API and cache."""

    async def search(args: GmailSearchArgs) -> GmailSearchResult:
        ids, _next = api.list_message_ids(q=args.query, page_token=None)
        refs = [
            _ref_from_message(api.get_message(message_id, fmt="metadata"))
            for message_id in ids[: args.max_results]
        ]
        return GmailSearchResult(messages=refs)

    async def get_message(args: GetMessageArgs) -> MessageDetail:
        return _detail_from_message(api.get_message(args.message_id, fmt="full"))

    async def list_threads(args: ListThreadsArgs) -> ThreadList:
        ids, _next = api.list_threads(q=args.query, page_token=None)
        return ThreadList(
            threads=[ThreadRef(thread_id=thread_id) for thread_id in ids[: args.max_results]]
        )

    async def get_thread(args: GetThreadArgs) -> ThreadDetail:
        thread = api.get_thread(args.thread_id)
        messages_obj = thread.get("messages")
        messages = messages_obj if isinstance(messages_obj, list) else []
        return ThreadDetail(
            messages=[
                _detail_from_message(cast(Mapping[str, object], message))
                for message in messages
                if isinstance(message, Mapping)
            ]
        )

    async def list_unread(args: ListUnreadArgs) -> GmailSearchResult:
        category = MailCategory(args.category) if args.category is not None else None
        return GmailSearchResult(
            messages=[_ref_from_cached(row) for row in cache.list_unread(category)]
        )

    return [
        ToolSpec(
            name="search",
            description="Search the owner's Gmail mailbox by query.",
            args_schema=GmailSearchArgs,
            return_schema=GmailSearchResult,
            callable_ref=search,
            action_risk=ActionRisk.READ,
        ),
        ToolSpec(
            name="get_message",
            description="Read one Gmail message body marked as untrusted.",
            args_schema=GetMessageArgs,
            return_schema=MessageDetail,
            callable_ref=get_message,
            action_risk=ActionRisk.READ,
        ),
        ToolSpec(
            name="list_threads",
            description="List Gmail threads matching a query.",
            args_schema=ListThreadsArgs,
            return_schema=ThreadList,
            callable_ref=list_threads,
            action_risk=ActionRisk.READ,
        ),
        ToolSpec(
            name="get_thread",
            description="Read one Gmail thread with bodies marked as untrusted.",
            args_schema=GetThreadArgs,
            return_schema=ThreadDetail,
            callable_ref=get_thread,
            action_risk=ActionRisk.READ,
        ),
        ToolSpec(
            name="list_unread",
            description="List unread Gmail messages from the local metadata cache.",
            args_schema=ListUnreadArgs,
            return_schema=GmailSearchResult,
            callable_ref=list_unread,
            action_risk=ActionRisk.READ,
        ),
    ]


def _detail_from_message(msg: Mapping[str, object]) -> MessageDetail:
    labels = _labels(msg)
    _nonce, marked = spotlight(extract_body_text(msg))
    return MessageDetail(
        header=extract_headers(msg),
        body_spotlighted=marked,
        category=categorize(labels).value,
        has_attachments=bool(list_attachment_parts(msg)),
    )


def _ref_from_message(msg: Mapping[str, object]) -> MessageRef:
    headers = extract_headers(msg)
    labels = _labels(msg)
    return MessageRef(
        message_id=str(msg.get("id", "")),
        thread_id=str(msg.get("threadId", "")),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        date_iso=_date_iso(msg.get("internalDate")),
        category=categorize(labels).value,
        unread="UNREAD" in labels,
    )


def _ref_from_cached(row: CachedMessage) -> MessageRef:
    return MessageRef(
        message_id=row.message_id,
        thread_id=row.thread_id,
        sender=row.sender,
        subject=row.subject,
        date_iso=_date_iso(row.internal_date_ms),
        category=row.category.value,
        unread=row.unread,
    )


def _labels(msg: Mapping[str, object]) -> tuple[str, ...]:
    value = msg.get("labelIds")
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return ()


def _date_iso(value: object) -> str:
    millis = 0
    if isinstance(value, int):
        millis = value
    elif isinstance(value, str) and value.isdecimal():
        millis = int(value)
    return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()
