"""Headless pause-to-ask inbox for owner decisions.

Questions are stored in the owner-private SQLCipher scope. The ntfy notice is
intentionally content-free: it carries only a static response prompt plus the
unguessable question id, never the sensitive question text.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from artemis import paths
from artemis.agentic.types import OwnerInbox
from artemis.config import Settings
from artemis.data.sqlcipher import set_row_factory, sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.proactive.hit_handler import OutboundMessage
from artemis.proactive.hook_types import DeliverySpec

INBOX_NOTICE_TITLE = "Artemis needs a decision"
INBOX_NOTICE_BODY_PREFIX = "Response required for question id: "

Deliver = Callable[[list[OutboundMessage]], int]


@dataclass(frozen=True)
class AgentQuestion:
    """One owner-private question row."""

    id: str
    prompt: str
    options: tuple[str, ...]
    answer: str | None
    created_at: str
    resolved_at: str | None


class AgentInbox:
    """Owner-private durable store plus in-process waiters for agent questions."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider
        self._waiters: dict[str, asyncio.Future[str]] = {}

    def _db_path(self) -> Path:
        return paths.scope_dir(self._settings, OWNER_PRIVATE) / "agentic" / "agent_inbox.db"

    def _connect(self) -> sqlite3.Connection:
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(db_path, key.as_hex())
        set_row_factory(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_question ("
            "id TEXT PRIMARY KEY, "
            "prompt TEXT NOT NULL, "
            "options_json TEXT NOT NULL, "
            "answer TEXT, "
            "created_at TEXT NOT NULL, "
            "resolved_at TEXT)"
        )
        return conn

    def put(self, prompt: str, options: tuple[str, ...] = ()) -> str:
        """Persist a pending owner question and return its unguessable id."""
        question_id = secrets.token_urlsafe(32)
        created_at = _now_iso()
        options_json = json.dumps(list(options), separators=(",", ":"))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agent_question "
                "(id, prompt, options_json, answer, created_at, resolved_at) "
                "VALUES (?, ?, ?, NULL, ?, NULL)",
                (question_id, prompt, options_json, created_at),
            )
        return question_id

    def pending(self) -> list[AgentQuestion]:
        """List unresolved questions for CLI/API owner resolution surfaces."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, prompt, options_json, answer, created_at, resolved_at "
                "FROM agent_question WHERE answer IS NULL ORDER BY created_at, id"
            ).fetchall()
        return [_question_from_row(row) for row in rows]

    def resolve(self, question_id: str, answer: str) -> None:
        """Persist the first answer for ``question_id`` and release its waiter."""
        resolved_at = _now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE agent_question SET answer = ?, resolved_at = ? "
                "WHERE id = ? AND answer IS NULL",
                (answer, resolved_at, question_id),
            )
            did_resolve = cursor.rowcount == 1

        if did_resolve:
            waiter = self._waiters.get(question_id)
            if waiter is not None and not waiter.done():
                waiter.set_result(answer)

    def get(self, question_id: str) -> AgentQuestion | None:
        """Return one question row, if present."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, prompt, options_json, answer, created_at, resolved_at "
                "FROM agent_question WHERE id = ?",
                (question_id,),
            ).fetchone()
        return None if row is None else _question_from_row(row)

    async def wait_for_answer(self, question_id: str) -> str:
        """Block until ``question_id`` has an answer in this process."""
        existing = self.get(question_id)
        if existing is not None and existing.answer is not None:
            return existing.answer

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[str] = loop.create_future()
        self._waiters[question_id] = waiter
        try:
            return await waiter
        finally:
            if self._waiters.get(question_id) is waiter:
                self._waiters.pop(question_id, None)


class AskOwnerTool(OwnerInbox):
    """OwnerInbox implementation that persists, notifies over ntfy, then waits."""

    def __init__(self, inbox: AgentInbox, ntfy: Deliver) -> None:
        self._inbox = inbox
        self._ntfy = ntfy

    async def ask(
        self, question: str, *, options: tuple[str, ...] = (), timeout_s: int = 0
    ) -> str | None:
        """Ask the owner, returning ``None`` instead of raising on timeout."""
        question_id = self._inbox.put(question, options)
        self._ntfy([_notice_for(question_id)])

        try:
            if timeout_s == 0:
                return await self._inbox.wait_for_answer(question_id)
            return await asyncio.wait_for(
                self._inbox.wait_for_answer(question_id),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:  # noqa: UP041 - spec requires catching asyncio.TimeoutError.
            return None


def _notice_for(question_id: str) -> OutboundMessage:
    return OutboundMessage(
        title=INBOX_NOTICE_TITLE,
        body=f"{INBOX_NOTICE_BODY_PREFIX}{question_id}",
        urgency="normal",
        disposition="immediate",
        tier=0,
        delivery=DeliverySpec(
            priority="default",
            tags=["question"],
            actions=[
                {
                    "action": "view",
                    "label": "Resolve",
                    "url": f"artemis://agent-inbox/resolve/{question_id}",
                }
            ],
        ),
        dedup_key="agent-inbox",
        dedup_value=question_id,
        source="agentic.inbox",
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _question_from_row(row: sqlite3.Row) -> AgentQuestion:
    options_raw = json.loads(str(row["options_json"]))
    options = tuple(str(item) for item in options_raw) if isinstance(options_raw, list) else ()
    return AgentQuestion(
        id=str(row["id"]),
        prompt=str(row["prompt"]),
        options=options,
        answer=None if row["answer"] is None else str(row["answer"]),
        created_at=str(row["created_at"]),
        resolved_at=None if row["resolved_at"] is None else str(row["resolved_at"]),
    )
