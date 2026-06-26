"""Owner-private SQLite checkpoint store for resumable agentic execution.

One row is stored per task id: executor state, plan JSON, current step index,
and the last output that was verified. The store uses the same owner-private
SQLCipher construction as other owner-private Artemis stores.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from artemis import paths
from artemis.agentic.types import CheckpointRow, ExecutorState, Plan
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE

logger = logging.getLogger(__name__)


class CheckpointCorruptedError(Exception):
    """Raised when a checkpoint row cannot be decoded."""

    def __init__(self, task_id: str) -> None:
        super().__init__(task_id)


class SqliteCheckpointStore:
    """SQLCipher-backed checkpoint store for owner-private resume state."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider

    def _db_path(self) -> Path:
        return paths.scope_dir(self._settings, OWNER_PRIVATE) / "agentic" / "agent_checkpoint.db"

    def _connect(self) -> sqlite3.Connection:
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(db_path, key.as_hex())
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_checkpoint ("
            "task_id TEXT PRIMARY KEY, "
            "state TEXT NOT NULL, "
            "plan_json TEXT NOT NULL, "
            "step_index INTEGER NOT NULL, "
            "last_verified_output TEXT)"
        )
        return conn

    def save(
        self,
        task_id: str,
        state: ExecutorState,
        plan: Plan,
        step_index: int,
        last_verified_output: str | None,
    ) -> None:
        """Persist one checkpoint row for ``task_id``."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agent_checkpoint "
                "(task_id, state, plan_json, step_index, last_verified_output) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, state.value, plan.model_dump_json(), step_index, last_verified_output),
            )

    def load(self, task_id: str) -> CheckpointRow | None:
        """Return the checkpoint row for ``task_id``, if one exists."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT task_id, state, plan_json, step_index, last_verified_output "
                "FROM agent_checkpoint WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None

        try:
            plan = Plan.model_validate_json(str(row["plan_json"]))
        except ValidationError as exc:
            logger.warning(
                "Corrupt checkpoint row for task_id %s: %s",
                task_id,
                type(exc).__name__,
            )
            raise CheckpointCorruptedError(task_id) from exc

        return CheckpointRow(
            task_id=str(row["task_id"]),
            state=ExecutorState(str(row["state"])),
            plan=plan,
            step_index=int(row["step_index"]),
            last_verified_output=None
            if row["last_verified_output"] is None
            else str(row["last_verified_output"]),
        )
