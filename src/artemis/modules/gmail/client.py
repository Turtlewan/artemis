"""Read-only Gmail API port, fake, categorisation, and MIME helpers."""

from __future__ import annotations

import base64
import html
import importlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Protocol, cast

from artemis.integrations.google.credentials import GoogleCredentialsFactory

GMAIL_READONLY_SCOPE: Final = "https://www.googleapis.com/auth/gmail.readonly"


class MailCategory(StrEnum):
    """Gmail categories used by the split-depth ingest policy."""

    PRIMARY = "primary"
    UPDATES = "updates"
    FORUMS = "forums"
    PROMOTIONS = "promotions"
    SOCIAL = "social"
    SPAM = "spam"
    TRASH = "trash"


SIGNAL_CATEGORIES: Final = frozenset(
    {MailCategory.PRIMARY, MailCategory.UPDATES, MailCategory.FORUMS}
)


@dataclass(frozen=True)
class AttachmentRef:
    """Reference to one Gmail attachment part."""

    filename: str
    mime: str
    attachment_id: str
    size: int


class GmailApiPort(Protocol):
    """Synchronous Gmail API seam used by sync, ingest, and read tools."""

    def list_message_ids(self, *, q: str, page_token: str | None) -> tuple[list[str], str | None]:
        """Return message ids for a Gmail search page."""
        ...

    def get_message(
        self, message_id: str, *, fmt: Literal["full", "metadata"]
    ) -> Mapping[str, object]:
        """Return one message in Gmail API shape."""
        ...

    def list_history(
        self, *, start_history_id: str, page_token: str | None
    ) -> tuple[list[Mapping[str, object]], str | None, str]:
        """Return one History API page plus response-level history id."""
        ...

    def get_attachment(self, *, message_id: str, attachment_id: str) -> bytes:
        """Return decoded attachment bytes."""
        ...

    def current_history_id(self) -> str:
        """Return the mailbox current history id."""
        ...

    def get_thread(self, thread_id: str) -> Mapping[str, object]:
        """Return one Gmail thread."""
        ...

    def list_threads(self, *, q: str, page_token: str | None) -> tuple[list[str], str | None]:
        """Return thread ids for a Gmail search page."""
        ...


class GmailClient:
    """Read-only Gmail v1 client with lazy ``googleapiclient`` import."""

    def __init__(self, credentials_factory: GoogleCredentialsFactory) -> None:
        self._credentials_factory = credentials_factory
        self._service: object | None = None

    @property
    def _gmail(self) -> object:
        if self._service is None:
            discovery = importlib.import_module("googleapiclient.discovery")
            build = getattr(discovery, "build")
            self._service = build(
                "gmail",
                "v1",
                credentials=self._credentials_factory.authorized_credentials(),
                cache_discovery=False,
            )
        return self._service

    def list_message_ids(self, *, q: str, page_token: str | None) -> tuple[list[str], str | None]:
        users = getattr(self._gmail, "users")()
        messages = getattr(users, "messages")()
        request = getattr(messages, "list")(userId="me", q=q, pageToken=page_token)
        resp = cast(Mapping[str, object], getattr(request, "execute")())
        rows = _mapping_list(resp.get("messages"))
        return (
            [str(row["id"]) for row in rows if "id" in row],
            _optional_str(resp.get("nextPageToken")),
        )

    def get_message(
        self, message_id: str, *, fmt: Literal["full", "metadata"]
    ) -> Mapping[str, object]:
        users = getattr(self._gmail, "users")()
        messages = getattr(users, "messages")()
        request = getattr(messages, "get")(userId="me", id=message_id, format=fmt)
        return cast(Mapping[str, object], getattr(request, "execute")())

    def list_history(
        self, *, start_history_id: str, page_token: str | None
    ) -> tuple[list[Mapping[str, object]], str | None, str]:
        users = getattr(self._gmail, "users")()
        history = getattr(users, "history")()
        request = getattr(history, "list")(
            userId="me", startHistoryId=start_history_id, pageToken=page_token
        )
        resp = cast(Mapping[str, object], getattr(request, "execute")())
        return (
            _mapping_list(resp.get("history")),
            _optional_str(resp.get("nextPageToken")),
            str(resp.get("historyId", "")),
        )

    def get_attachment(self, *, message_id: str, attachment_id: str) -> bytes:
        users = getattr(self._gmail, "users")()
        attachments = getattr(getattr(users, "messages")(), "attachments")()
        request = getattr(attachments, "get")(userId="me", messageId=message_id, id=attachment_id)
        resp = cast(Mapping[str, object], getattr(request, "execute")())
        data = resp.get("data")
        if not isinstance(data, str):
            return b""
        return _b64decode(data)

    def current_history_id(self) -> str:
        users = getattr(self._gmail, "users")()
        request = getattr(users, "getProfile")(userId="me")
        resp = cast(Mapping[str, object], getattr(request, "execute")())
        return str(resp.get("historyId", ""))

    def get_thread(self, thread_id: str) -> Mapping[str, object]:
        users = getattr(self._gmail, "users")()
        threads = getattr(users, "threads")()
        request = getattr(threads, "get")(userId="me", id=thread_id)
        return cast(Mapping[str, object], getattr(request, "execute")())

    def list_threads(self, *, q: str, page_token: str | None) -> tuple[list[str], str | None]:
        users = getattr(self._gmail, "users")()
        threads = getattr(users, "threads")()
        request = getattr(threads, "list")(userId="me", q=q, pageToken=page_token)
        resp = cast(Mapping[str, object], getattr(request, "execute")())
        rows = _mapping_list(resp.get("threads"))
        return (
            [str(row["id"]) for row in rows if "id" in row],
            _optional_str(resp.get("nextPageToken")),
        )


class FakeGmailApi:
    """Deterministic in-memory Gmail API fake for off-hardware tests."""

    def __init__(
        self,
        *,
        messages: Mapping[str, Mapping[str, object]] | None = None,
        attachments: Mapping[tuple[str, str], bytes] | None = None,
        history_pages: Sequence[tuple[list[Mapping[str, object]], str | None, str]] | None = None,
        threads: Mapping[str, Mapping[str, object]] | None = None,
        history_id: str = "1",
    ) -> None:
        self.messages: dict[str, Mapping[str, object]] = dict(messages or {})
        self.attachments: dict[tuple[str, str], bytes] = dict(attachments or {})
        self.history_pages = list(history_pages or [])
        self.threads: dict[str, Mapping[str, object]] = dict(threads or {})
        self.history_id = history_id

    def list_message_ids(self, *, q: str, page_token: str | None) -> tuple[list[str], str | None]:
        _ = q, page_token
        return (list(self.messages), None)

    def get_message(
        self, message_id: str, *, fmt: Literal["full", "metadata"]
    ) -> Mapping[str, object]:
        _ = fmt
        return self.messages[message_id]

    def list_history(
        self, *, start_history_id: str, page_token: str | None
    ) -> tuple[list[Mapping[str, object]], str | None, str]:
        _ = start_history_id
        index = int(page_token) if page_token is not None else 0
        if index >= len(self.history_pages):
            return ([], None, self.history_id)
        return self.history_pages[index]

    def get_attachment(self, *, message_id: str, attachment_id: str) -> bytes:
        return self.attachments[(message_id, attachment_id)]

    def current_history_id(self) -> str:
        return self.history_id

    def get_thread(self, thread_id: str) -> Mapping[str, object]:
        if thread_id in self.threads:
            return self.threads[thread_id]
        messages = [msg for msg in self.messages.values() if msg.get("threadId") == thread_id]
        return {"id": thread_id, "messages": messages}

    def list_threads(self, *, q: str, page_token: str | None) -> tuple[list[str], str | None]:
        _ = q, page_token
        if self.threads:
            return (list(self.threads), None)
        return (sorted({str(msg.get("threadId", "")) for msg in self.messages.values()}), None)


def categorize(label_ids: Sequence[str]) -> MailCategory:
    """Map Gmail label ids to the connector's split-depth category."""
    labels = set(label_ids)
    if "SPAM" in labels:
        return MailCategory.SPAM
    if "TRASH" in labels:
        return MailCategory.TRASH
    if "CATEGORY_PROMOTIONS" in labels:
        return MailCategory.PROMOTIONS
    if "CATEGORY_SOCIAL" in labels:
        return MailCategory.SOCIAL
    if "CATEGORY_UPDATES" in labels:
        return MailCategory.UPDATES
    if "CATEGORY_FORUMS" in labels:
        return MailCategory.FORUMS
    return MailCategory.PRIMARY


def is_signal(category: MailCategory) -> bool:
    """Return whether a category receives body, attachment, and memory processing."""
    return category in SIGNAL_CATEGORIES


def extract_headers(msg: Mapping[str, object]) -> dict[str, str]:
    """Extract selected message headers using lowercase keys."""
    payload = _mapping(msg.get("payload"))
    headers = _mapping_list(payload.get("headers"))
    wanted = {"from", "to", "subject", "date"}
    result: dict[str, str] = {}
    for header in headers:
        name = header.get("name")
        value = header.get("value")
        if isinstance(name, str) and isinstance(value, str) and name.lower() in wanted:
            result[name.lower()] = value
    return result


def extract_body_text(msg: Mapping[str, object]) -> str:
    """Return decoded text/plain body, falling back to stripped text/html."""
    payload = _mapping(msg.get("payload"))
    plain_parts: list[str] = []
    html_parts: list[str] = []
    _collect_body_parts(payload, plain_parts, html_parts)
    if plain_parts:
        return _clean_text("\n".join(plain_parts))
    return _clean_text(_strip_html("\n".join(html_parts)))


def list_attachment_parts(msg: Mapping[str, object]) -> list[AttachmentRef]:
    """Return attachment parts without downloading attachment bytes."""
    refs: list[AttachmentRef] = []
    _collect_attachment_parts(_mapping(msg.get("payload")), refs)
    return refs


def _collect_body_parts(
    payload: Mapping[str, object], plain: list[str], html_parts: list[str]
) -> None:
    mime_type = payload.get("mimeType")
    body = _mapping(payload.get("body"))
    data = body.get("data")
    filename = payload.get("filename")
    if isinstance(data, str) and not filename:
        decoded = _b64decode(data).decode("utf-8", errors="replace")
        if mime_type == "text/plain":
            plain.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(decoded)
    for part in _mapping_list(payload.get("parts")):
        _collect_body_parts(part, plain, html_parts)


def _collect_attachment_parts(payload: Mapping[str, object], refs: list[AttachmentRef]) -> None:
    body = _mapping(payload.get("body"))
    attachment_id = body.get("attachmentId")
    filename = payload.get("filename")
    if isinstance(attachment_id, str) and isinstance(filename, str) and filename:
        size = body.get("size")
        refs.append(
            AttachmentRef(
                filename=filename,
                mime=str(payload.get("mimeType", "application/octet-stream")),
                attachment_id=attachment_id,
                size=size if isinstance(size, int) else 0,
            )
        )
    for part in _mapping_list(payload.get("parts")):
        _collect_attachment_parts(part, refs)


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if isinstance(value, list):
        return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]
    return []


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _b64decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _strip_html(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(no_tags)


def _clean_text(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()
