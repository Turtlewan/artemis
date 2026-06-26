from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from artemis import paths
from artemis.agentic.checkpoint import CheckpointCorruptedError, SqliteCheckpointStore
from artemis.agentic.types import CheckpointStore, ExecutorState, Plan, PlanStep
from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError
from artemis.identity.scope import OWNER_PRIVATE


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")


def _key_provider(*, owner_unlocked: bool = True) -> FakeKeyProvider:
    keys = {OWNER_PRIVATE: b"1" * 32} if owner_unlocked else {}
    return FakeKeyProvider(keys, owner_unlocked=owner_unlocked)


def _store(tmp_path: Path, *, owner_unlocked: bool = True) -> SqliteCheckpointStore:
    return SqliteCheckpointStore(_settings(tmp_path), _key_provider(owner_unlocked=owner_unlocked))


def _plan(task_id: str = "task-1") -> Plan:
    return Plan(
        task_id=task_id,
        steps=(
            PlanStep(
                id="step-1",
                description="Do the first thing",
                tool_ref="tool.alpha",
                args={"limit": 3, "dry_run": True},
                verify="Check the first thing",
            ),
        ),
    )


def test_checkpoint_store_round_trips_row(tmp_path: Path) -> None:
    store: CheckpointStore = _store(tmp_path)
    plan = _plan()

    store.save("task-1", ExecutorState.ACTING, plan, 1, "verified tool output")

    row = store.load("task-1")
    assert row is not None
    assert row.task_id == "task-1"
    assert row.state is ExecutorState.ACTING
    assert row.plan == plan
    assert row.step_index == 1
    assert row.last_verified_output == "verified tool output"


def test_checkpoint_store_returns_none_for_missing_task(tmp_path: Path) -> None:
    assert _store(tmp_path).load("missing") is None


def test_checkpoint_store_loads_after_reconstruct(tmp_path: Path) -> None:
    first = _store(tmp_path)
    plan = _plan("task-durable")
    first.save("task-durable", ExecutorState.VERIFYING, plan, 2, None)

    second = _store(tmp_path)
    row = second.load("task-durable")

    assert row is not None
    assert row.state is ExecutorState.VERIFYING
    assert row.plan == plan
    assert row.step_index == 2
    assert row.last_verified_output is None


def test_checkpoint_store_uses_owner_private_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = SqliteCheckpointStore(settings, _key_provider())

    store.save("task-1", ExecutorState.PLANNING, _plan(), 0, None)

    expected = paths.scope_dir(settings, OWNER_PRIVATE) / "agentic" / "agent_checkpoint.db"
    assert store._db_path() == expected
    assert expected.exists()
    assert expected.is_relative_to(paths.scope_dir(settings, OWNER_PRIVATE))


def test_checkpoint_store_locked_scope_raises_without_fallback(tmp_path: Path) -> None:
    store = _store(tmp_path, owner_unlocked=False)

    with pytest.raises(ScopeLockedError):
        store.save("task-1", ExecutorState.PLANNING, _plan(), 0, None)

    assert not (tmp_path / "dev" / OWNER_PRIVATE / "agentic" / "agent_checkpoint.db").exists()


def test_checkpoint_store_does_not_log_plan_or_output(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path)
    plan = _plan()
    plan_json = plan.model_dump_json()
    last_verified_output = "sensitive stdout from owner tool"

    caplog.set_level(logging.DEBUG)
    store.save("task-1", ExecutorState.ACTING, plan, 1, last_verified_output)
    assert store.load("task-1") is not None

    assert plan_json not in caplog.text
    assert last_verified_output not in caplog.text


def test_checkpoint_store_corrupted_plan_json_raises_redacted_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path)
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO agent_checkpoint "
            "(task_id, state, plan_json, step_index, last_verified_output) "
            "VALUES (?, ?, ?, ?, ?)",
            ("task-corrupt", ExecutorState.ACTING.value, '{"task_id": 7}', 0, "private output"),
        )

    caplog.set_level(logging.WARNING, logger="artemis.agentic.checkpoint")
    with pytest.raises(CheckpointCorruptedError) as exc_info:
        store.load("task-corrupt")

    assert str(exc_info.value) == "task-corrupt"
    assert exc_info.value.args == ("task-corrupt",)
    assert "task_id" not in str(exc_info.value).replace("task-corrupt", "")
    assert "Field required" not in str(exc_info.value)
    assert "private output" not in caplog.text
    assert '{"task_id": 7}' not in caplog.text
    assert "Input should be a valid string" not in caplog.text
    assert "task-corrupt" in caplog.text


def test_checkpoint_store_has_expected_schema(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save("task-1", ExecutorState.PLANNING, _plan(), 0, None)

    with sqlite3.connect(store._db_path()) as conn:
        columns = conn.execute("PRAGMA table_info(agent_checkpoint)").fetchall()

    assert [column[1] for column in columns] == [
        "task_id",
        "state",
        "plan_json",
        "step_index",
        "last_verified_output",
    ]
