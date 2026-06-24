"""Off-hardware tests for CAL-b calendar write gating and activity log."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import ModuleManifest
from artemis.modules.calendar.activity_log import ActivityLog
from artemis.modules.calendar.cache import EventCacheStore
from artemis.modules.calendar.client import FakeCalendarClient
from artemis.modules.calendar.gating import GateDecision, classify
from artemis.modules.calendar.manifest import CalendarTools, make_calendar_manifest
from artemis.modules.calendar.preferences import CalPrefs, PreferencesStore
from artemis.modules.calendar.write_tools import (
    BlockFocusTimeArgs,
    CalendarWriteError,
    CalendarWriteTools,
    CancelEventArgs,
    CreateEventArgs,
    RespondToInviteArgs,
    StagedResult,
    UpdateEventArgs,
    WriteResult,
)
from artemis.ports.types import Vector
from artemis.registry import ToolRegistry
from artemis.staging.model import ActionStatus, PendingAction
from artemis.staging.service import ActionStagingService
from artemis.staging.store import PendingActionStore


class FakeEmbedder:
    """Deterministic test embedder for registry construction."""

    @property
    def dimension(self) -> int:
        return 16

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vec(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._hash_vec(query)

    def _hash_vec(self, text: str) -> Vector:
        vec = [0.0] * self.dimension
        for word in text.lower().split():
            vec[hashlib.sha256(word.encode()).digest()[0] % self.dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        return [value / norm for value in vec] if norm else vec


class FakeEventCacheStore:
    """Cache spy with the live two-argument invalidate signature."""

    def __init__(self) -> None:
        self.invalidations: list[tuple[str, str]] = []

    def invalidate(self, event_id: str, calendar_id: str) -> None:
        self.invalidations.append((event_id, calendar_id))


class FakeActionStagingService:
    """Sync stage spy matching ``ActionStagingService.stage``."""

    def __init__(self) -> None:
        self.staged: list[PendingAction] = []

    def stage(
        self,
        module: str,
        tool: str,
        args: dict[str, object],
        summary: str,
        *,
        ttl: timedelta | None = None,
    ) -> PendingAction:
        del ttl
        now = datetime.now(tz=UTC)
        action = PendingAction(
            id=f"fake-id-{len(self.staged) + 1}",
            module=module,
            tool=tool,
            args=args,
            summary=summary,
            action_class="takes-action",
            status=ActionStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        self.staged.append(action)
        return action


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")


def _key_provider(*, unlocked: bool = True) -> FakeKeyProvider:
    keys = {OWNER_PRIVATE: b"1" * 32} if unlocked else {}
    return FakeKeyProvider(keys, owner_unlocked=unlocked)


def _client() -> FakeCalendarClient:
    return FakeCalendarClient(
        calendar_list=[{"id": "primary", "summary": "Primary"}],
        events_by_calendar={
            "primary": [
                {
                    "id": "e1",
                    "summary": "Solo",
                    "start": {"dateTime": "2026-06-24T09:00:00Z"},
                    "end": {"dateTime": "2026-06-24T10:00:00Z"},
                    "status": "confirmed",
                    "attendees": [{"email": "me@x.com"}],
                },
                {
                    "id": "e2",
                    "summary": "Team",
                    "start": {"dateTime": "2026-06-24T11:00:00Z"},
                    "end": {"dateTime": "2026-06-24T12:00:00Z"},
                    "status": "confirmed",
                    "attendees": [{"email": "other@x.com"}],
                },
            ]
        },
        free_busy_response={},
    )


def _write_tools(
    tmp_path: Path,
    *,
    client: FakeCalendarClient | None = None,
    staging: FakeActionStagingService | ActionStagingService | None = None,
) -> tuple[CalendarWriteTools, FakeCalendarClient, FakeEventCacheStore, ActivityLog, object]:
    fake_client = client or _client()
    cache = FakeEventCacheStore()
    stage_service = staging or FakeActionStagingService()
    log = ActivityLog(_settings(tmp_path), _key_provider())
    tools = CalendarWriteTools(
        fake_client,
        cast(EventCacheStore, cache),
        CalPrefs(owner_email="me@x.com", default_write_calendar="primary"),
        cast(ActionStagingService, stage_service),
        log,
    )
    return tools, fake_client, cache, log, stage_service


def test_classifier_truth_table() -> None:
    cases = [
        ("block_focus_time", [], "me@x.com", GateDecision.AUTO),
        ("set_reminders", ["me@x.com", "other@x.com"], "me@x.com", GateDecision.AUTO),
        ("respond_to_invite", [], "me@x.com", GateDecision.GATED),
        ("create_event", [], "me@x.com", GateDecision.AUTO),
        ("create_event", ["me@x.com"], "me@x.com", GateDecision.AUTO),
        ("create_event", ["me@x.com", "other@x.com"], "me@x.com", GateDecision.GATED),
        ("cancel_event", ["other@x.com"], "me@x.com", GateDecision.GATED),
        ("create_event", [], "", GateDecision.GATED),
        ("update_event", ["other@x.com"], "me@x.com", GateDecision.GATED),
    ]
    for tool_name, attendees, owner_email, expected in cases:
        assert classify(tool_name, attendees, owner_email) is expected


@pytest.mark.asyncio
async def test_auto_path_executes_logs_and_does_not_stage(tmp_path: Path) -> None:
    tools, client, _, log, staging = _write_tools(tmp_path)

    result = await tools.block_focus_time(
        BlockFocusTimeArgs(
            start_datetime="2026-06-24T13:00:00Z",
            end_datetime="2026-06-24T14:00:00Z",
        )
    )

    assert isinstance(result, WriteResult)
    assert len(client.write_calls["create_event"]) == 1
    entries = log.recent()
    assert len(entries) == 1
    assert entries[0].tool_name == "calendar.block_focus_time"
    assert entries[0].result_status == "executed"
    fake_staging = cast(FakeActionStagingService, staging)
    assert fake_staging.staged == []


@pytest.mark.asyncio
async def test_gated_path_stages_only_and_does_not_log(tmp_path: Path) -> None:
    tools, client, _, log, staging = _write_tools(tmp_path)

    result = await tools.create_event(
        CreateEventArgs(
            summary="Team sync",
            start_datetime="2026-06-24T13:00:00Z",
            end_datetime="2026-06-24T14:00:00Z",
            attendee_emails=["other@x.com"],
        )
    )

    assert isinstance(result, StagedResult)
    assert client.write_calls["create_event"] == []
    fake_staging = cast(FakeActionStagingService, staging)
    assert len(fake_staging.staged) == 1
    action = fake_staging.staged[0]
    assert action.module == "calendar"
    assert action.tool == "calendar.create_event"
    assert action.args["summary"] == "Team sync"
    assert action.summary
    assert action.status is ActionStatus.PENDING
    assert log.recent() == []


@pytest.mark.asyncio
async def test_approve_dispatches_raw_twin_without_restaging(tmp_path: Path) -> None:
    client = _client()
    registry = ToolRegistry(FakeEmbedder())
    store = PendingActionStore(_settings(tmp_path), _key_provider())
    staging = ActionStagingService(store, registry)
    tools, _, _, _, _ = _write_tools(tmp_path, client=client, staging=staging)
    read_tools = CalendarTools(
        cast(EventCacheStore, FakeEventCacheStore()),
        cast(PreferencesStore, object()),
        client,
    )
    manifest = make_calendar_manifest(read_tools, tools)
    registry.register(manifest)

    result = await tools.create_event(
        CreateEventArgs(
            summary="Team sync",
            start_datetime="2026-06-24T13:00:00Z",
            end_datetime="2026-06-24T14:00:00Z",
            attendee_emails=["other@x.com"],
        )
    )
    assert isinstance(result, StagedResult)
    assert client.write_calls["create_event"] == []

    approved = await staging.approve(result.pending_action_id)

    assert len(client.write_calls["create_event"]) == 1
    assert approved.status is ActionStatus.APPROVED
    assert store.list_pending() == []


@pytest.mark.asyncio
async def test_rsvp_is_always_gated(tmp_path: Path) -> None:
    tools, client, _, _, staging = _write_tools(tmp_path)

    result = await tools.respond_to_invite(RespondToInviteArgs(event_id="e1", response="accepted"))

    assert isinstance(result, StagedResult)
    assert client.write_calls["respond_to_invite"] == []
    fake_staging = cast(FakeActionStagingService, staging)
    assert len(fake_staging.staged) == 1
    assert fake_staging.staged[0].tool == "calendar.respond_to_invite"
    assert fake_staging.staged[0].summary


@pytest.mark.asyncio
async def test_recurrence_scope_threaded_on_auto_cancel(tmp_path: Path) -> None:
    tools, client, _, _, _ = _write_tools(tmp_path)

    await tools.cancel_event(CancelEventArgs(event_id="e1", recurrence_scope="THIS_AND_FOLLOWING"))

    assert client.write_calls["cancel_event"][0]["recurrence_scope"] == "THIS_AND_FOLLOWING"


@pytest.mark.asyncio
async def test_write_failure_surfaces_without_activity_log(tmp_path: Path) -> None:
    client = _client()
    client.raise_on_write.add("create_event")
    tools, _, _, log, _ = _write_tools(tmp_path, client=client)

    with pytest.raises(CalendarWriteError):
        await tools.block_focus_time(
            BlockFocusTimeArgs(
                start_datetime="2026-06-24T13:00:00Z",
                end_datetime="2026-06-24T14:00:00Z",
            )
        )

    assert log.recent() == []


def test_locked_activity_log_raises_scope_locked_error(tmp_path: Path) -> None:
    log = ActivityLog(_settings(tmp_path), _key_provider(unlocked=False))

    with pytest.raises(ScopeLockedError):
        log.record(
            WriteResult(
                event_id="e1",
                summary="Focus",
                tool_name="calendar.block_focus_time",
                status="executed",
            )
        )

    with pytest.raises(ScopeLockedError):
        log.recent()


@pytest.mark.asyncio
async def test_cache_invalidation_uses_event_and_calendar_id(tmp_path: Path) -> None:
    tools, _, cache, _, _ = _write_tools(tmp_path)

    await tools.update_event(UpdateEventArgs(event_id="e1", summary="Updated"))

    assert cache.invalidations == [("e1", "primary")]


def test_manifest_factory_adds_write_tools_with_bare_names(tmp_path: Path) -> None:
    tools, client, _, _, _ = _write_tools(tmp_path)
    read_tools = CalendarTools(
        cast(EventCacheStore, FakeEventCacheStore()),
        cast(PreferencesStore, object()),
        client,
    )

    manifest: ModuleManifest = make_calendar_manifest(read_tools, tools)

    assert len(manifest.tools) == 21
    assert all("." not in tool.name for tool in manifest.tools)
