"""Owner-private SQLCipher store for pending gated actions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.staging.model import ActionStatus, PendingAction


class PendingActionStore:
    """Persist pending actions in the owner-private SQLCipher scope."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self.settings = settings
        self.key_provider = key_provider

    def _db_path(self) -> Path:
        """Return the pending-action DB path under the owner-private scope.

        The on-hardware vault-path reconciliation is deferred to the same
        one-line adapter used by the token store once the Mini mount is present.
        """
        return paths.scope_dir(self.settings, OWNER_PRIVATE) / "staging" / "pending_actions.db"

    def _connect(self) -> sqlite3.Connection:
        """Open the DB with the owner DEK and ensure the schema exists.

        ``key_hex`` is deliberately local to this method and is never stored on
        ``self`` or at module scope; this bounds the immutable string lifetime to
        the connection setup path, consistent with the SQLCipher store pattern.
        """
        key = self.key_provider.dek_for_scope(OWNER_PRIVATE)
        key_hex = key.as_hex()
        self._db_path().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(self._db_path(), key_hex)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_actions (
                id TEXT PRIMARY KEY,
                module TEXT NOT NULL,
                tool TEXT NOT NULL,
                args TEXT NOT NULL,
                summary TEXT NOT NULL,
                action_class TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                result TEXT
            )
            """
        )
        conn.commit()
        return conn

    def stage(self, action: PendingAction) -> None:
        """Insert a new pending action."""
        if action.status is not ActionStatus.PENDING:
            raise ValueError("Only PENDING actions can be staged")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO pending_actions (
                    id, module, tool, args, summary, action_class, status,
                    created_at, expires_at, result
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._to_row(action),
            )
            conn.commit()

    def get(self, action_id: str) -> PendingAction:
        """Return one action by id, raising ``KeyError`` when absent."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT id, module, tool, args, summary, action_class, status,
                       created_at, expires_at, result
                FROM pending_actions
                WHERE id = ?
                """,
                (action_id,),
            ).fetchone()
        if row is None:
            raise KeyError(action_id)
        return self._from_row(row)

    def list_pending(self) -> list[PendingAction]:
        """Return pending actions ordered by creation time."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, module, tool, args, summary, action_class, status,
                       created_at, expires_at, result
                FROM pending_actions
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (ActionStatus.PENDING.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def set_status(
        self,
        action_id: str,
        status: ActionStatus,
        *,
        result: dict[str, object] | None = None,
    ) -> None:
        """Set an action status, optionally persisting an execution result."""
        with closing(self._connect()) as conn:
            if result is None:
                cursor = conn.execute(
                    "UPDATE pending_actions SET status = ? WHERE id = ?",
                    (status.value, action_id),
                )
            else:
                cursor = conn.execute(
                    "UPDATE pending_actions SET status = ?, result = ? WHERE id = ?",
                    (status.value, json.dumps(result), action_id),
                )
            conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(action_id)

    def set_status_conditional(
        self,
        action_id: str,
        new_status: ActionStatus,
        expected_status: ActionStatus,
    ) -> None:
        """Atomically change status only when the expected current status matches."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE pending_actions SET status = ? WHERE id = ? AND status = ?",
                (new_status.value, action_id, expected_status.value),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(
                f"Conditional status update failed for {action_id}: expected {expected_status}"
            )

    def _to_row(
        self, action: PendingAction
    ) -> tuple[str, str, str, str, str, str, str, str, str, str | None]:
        result = json.dumps(action.result) if action.result is not None else None
        return (
            action.id,
            action.module,
            action.tool,
            json.dumps(action.args),
            action.summary,
            action.action_class,
            action.status.value,
            action.created_at.isoformat(),
            action.expires_at.isoformat(),
            result,
        )

    def _from_row(self, row: tuple[object, ...]) -> PendingAction:
        result_text = cast(str | None, row[9])
        return PendingAction(
            id=cast(str, row[0]),
            module=cast(str, row[1]),
            tool=cast(str, row[2]),
            args=cast(dict[str, object], json.loads(cast(str, row[3]))),
            summary=cast(str, row[4]),
            action_class=cast(Literal["takes-action"], row[5]),
            status=ActionStatus(cast(str, row[6])),
            created_at=datetime_from_iso(cast(str, row[7])),
            expires_at=datetime_from_iso(cast(str, row[8])),
            result=cast(dict[str, object], json.loads(result_text))
            if result_text is not None
            else None,
        )


def datetime_from_iso(value: str) -> datetime:
    """Return a datetime parsed from an ISO-8601 string."""
    return datetime.fromisoformat(value)
