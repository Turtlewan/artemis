"""Tests for creating held tentative calendar events from sanitised extracts."""

from __future__ import annotations

import hashlib
import inspect
import math
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import cast

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import ActionRisk
from artemis.modules.calendar.activity_log import ActivityLog
from artemis.modules.calendar.cache import EventCacheStore
from artemis.modules.calendar.client import FakeCalendarClient
from artemis.modules.calendar.create_from_extract import (
    CreateFromExtractArgs,
    EventExtract,
    HeldEventIdArgs,
    HeldEventStatus,
    HeldEventStore,
    HeldTentativeEvent,
    HeldTentativeEventList,
    ListHeldEventsArgs,
    approve_held_event,
    create_from_extract,
    discard_held_event,
    list_held_events,
)
from artemis.modules.calendar.manifest import CalendarTools, make_calendar_manifest
from artemis.modules.calendar.preferences import CalPrefs, PreferencesStore
from artemis.modules.calendar.write_tools import CalendarWriteTools
from artemis.ports.types import Vector
from artemis.staging.model import ActionStatus, PendingAction
from artemis.staging.service import ActionStagingService


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


def _key_provider() -> FakeKeyProvider:
    return FakeKeyProvider({OWNER_PRIVATE: b"1" * 32}, owner_unlocked=True)


def _client() -> FakeCalendarClient:
    return FakeCalendarClient(
        calendar_list=[{"id": "primary", "summary": "Primary"}],
        events_by_calendar={"primary": []},
        free_busy_response={},
    )


def _store() -> HeldEventStore:
    return HeldEventStore(sqlite3.connect(":memory:"))


def _extract(
    *,
    raw_ref: str = "m1:0",
    attendees: tuple[str, ...] = (),
    summary: str = "SQ322 SIN to LHR",
) -> EventExtract:
    return EventExtract(
        summary=summary,
        start_datetime="2026-07-01T08:00:00Z",
        end_datetime="2026-07-01T18:00:00Z",
        location="Changi Airport",
        description="Sanitised itinerary summary",
        attendee_emails=attendees,
        raw_ref=raw_ref,
    )


def _write_tools(
    tmp_path: Path,
    *,
    client: FakeCalendarClient | None = None,
    staging: FakeActionStagingService | None = None,
) -> tuple[CalendarWriteTools, FakeCalendarClient, FakeActionStagingService]:
    fake_client = client or _client()
    stage_service = staging or FakeActionStagingService()
    tools = CalendarWriteTools(
        fake_client,
        cast(EventCacheStore, FakeEventCacheStore()),
        CalPrefs(owner_email="me@x.com", default_write_calendar="primary"),
        cast(ActionStagingService, stage_service),
        ActivityLog(_settings(tmp_path), _key_provider()),
    )
    return tools, fake_client, stage_service


@pytest.mark.asyncio
async def test_create_from_extract_holds_without_google_write() -> None:
    store = _store()
    client = _client()

    held = await create_from_extract(_extract(), event_type="flight", store=store)

    assert held.status is HeldEventStatus.HELD
    assert held.google_event_id is None
    assert held.pending_action_id is None
    assert client.write_calls["create_event"] == []
    assert store.get_held(held.id).summary == "SQ322 SIN to LHR"


@pytest.mark.asyncio
async def test_create_from_extract_is_idempotent_on_raw_ref() -> None:
    store = _store()

    first = await create_from_extract(_extract(raw_ref="m1:0"), event_type="flight", store=store)
    second = await create_from_extract(_extract(raw_ref="m1:0"), event_type="flight", store=store)

    assert second.id == first.id
    assert store.list_held(status="held") == [first]


@pytest.mark.asyncio
async def test_approve_self_only_executes_auto_google_write(tmp_path: Path) -> None:
    store = _store()
    write_tools, client, staging = _write_tools(tmp_path)
    held = await create_from_extract(_extract(raw_ref="m2:0"), event_type="flight", store=store)

    approved = await approve_held_event(held.id, store=store, write_tools=write_tools)

    assert approved.status is HeldEventStatus.APPROVED
    assert approved.google_event_id == "fake-event-1"
    assert approved.pending_action_id is None
    assert len(client.write_calls["create_event"]) == 1
    assert staging.staged == []


@pytest.mark.asyncio
async def test_approve_with_attendees_stages_without_google_write(tmp_path: Path) -> None:
    store = _store()
    write_tools, client, staging = _write_tools(tmp_path)
    held = await create_from_extract(
        _extract(raw_ref="m3:0", attendees=("other@x.com",)),
        event_type="meeting",
        store=store,
    )

    approved = await approve_held_event(held.id, store=store, write_tools=write_tools)

    assert approved.status is HeldEventStatus.APPROVED
    assert approved.google_event_id is None
    assert approved.pending_action_id == "fake-id-1"
    assert client.write_calls["create_event"] == []
    assert len(staging.staged) == 1
    action = staging.staged[0]
    assert action.module == "calendar"
    assert action.tool == "calendar.create_event"
    assert action.args["attendee_emails"] == ["other@x.com"]


@pytest.mark.asyncio
async def test_approve_already_approved_is_noop(tmp_path: Path) -> None:
    store = _store()
    write_tools, client, staging = _write_tools(tmp_path)
    held = await create_from_extract(_extract(raw_ref="m4:0"), event_type="flight", store=store)

    first = await approve_held_event(held.id, store=store, write_tools=write_tools)
    second = await approve_held_event(held.id, store=store, write_tools=write_tools)

    assert second == first
    assert len(client.write_calls["create_event"]) == 1
    assert staging.staged == []


@pytest.mark.asyncio
async def test_list_and_discard_are_internal_only(tmp_path: Path) -> None:
    store = _store()
    write_tools, client, staging = _write_tools(tmp_path)
    held = await create_from_extract(_extract(raw_ref="m5:0"), event_type="flight", store=store)
    approved_source = await create_from_extract(
        _extract(raw_ref="m6:0", summary="Dentist"),
        event_type="appointment",
        store=store,
    )
    await approve_held_event(approved_source.id, store=store, write_tools=write_tools)
    client.write_calls["create_event"].clear()

    held_only = await list_held_events(store=store, status="held")
    discarded = await discard_held_event(held.id, store=store)

    assert held_only == [held]
    assert discarded.status is HeldEventStatus.DISCARDED
    assert client.write_calls["create_event"] == []
    assert staging.staged == []


@pytest.mark.asyncio
async def test_discard_after_approve_is_noop(tmp_path: Path) -> None:
    # Status guard: discarding an already-APPROVED event must be a no-op so the
    # google_event_id/pending_action_id audit trail is never silently nulled.
    store = _store()
    write_tools, _client, _staging = _write_tools(tmp_path)
    held = await create_from_extract(_extract(raw_ref="m7:0"), event_type="flight", store=store)
    approved = await approve_held_event(held.id, store=store, write_tools=write_tools)
    assert approved.status is HeldEventStatus.APPROVED

    after_discard = await discard_held_event(held.id, store=store)

    assert after_discard.status is HeldEventStatus.APPROVED


def test_event_extract_has_no_raw_email_body_field() -> None:
    fields = set(EventExtract.model_fields)

    assert "raw_body" not in fields
    assert "body" not in fields
    assert "raw_subject" not in fields


def test_manifest_adds_held_event_tools_with_bare_names(tmp_path: Path) -> None:
    write_tools, client, _ = _write_tools(tmp_path)
    read_tools = CalendarTools(
        cast(EventCacheStore, FakeEventCacheStore()),
        cast(PreferencesStore, object()),
        client,
    )

    manifest = make_calendar_manifest(read_tools, write_tools, held_event_store=_store())

    tools = {tool.name: tool for tool in manifest.tools}
    assert {
        "create_from_extract",
        "approve_held_event",
        "list_held_events",
        "discard_held_event",
    } <= set(tools)
    assert all("." not in tool.name for tool in manifest.tools)
    assert tools["create_from_extract"].action_risk is ActionRisk.WRITE
    assert tools["approve_held_event"].action_risk is ActionRisk.HIGH_STAKES
    assert tools["list_held_events"].action_risk is ActionRisk.READ
    assert tools["discard_held_event"].action_risk is ActionRisk.WRITE
    create_ref = cast(partial[object], tools["create_from_extract"].callable_ref)
    approve_ref = cast(partial[object], tools["approve_held_event"].callable_ref)
    list_ref = cast(partial[object], tools["list_held_events"].callable_ref)
    discard_ref = cast(partial[object], tools["discard_held_event"].callable_ref)
    assert inspect.iscoroutinefunction(create_ref.func)
    assert inspect.iscoroutinefunction(approve_ref.func)
    assert inspect.iscoroutinefunction(list_ref.func)
    assert inspect.iscoroutinefunction(discard_ref.func)


@pytest.mark.asyncio
async def test_manifest_callables_execute_with_injected_store(tmp_path: Path) -> None:
    store = _store()
    write_tools, client, staging = _write_tools(tmp_path)
    read_tools = CalendarTools(
        cast(EventCacheStore, FakeEventCacheStore()),
        cast(PreferencesStore, object()),
        client,
    )
    manifest = make_calendar_manifest(read_tools, write_tools, held_event_store=store)
    tools = {tool.name: tool for tool in manifest.tools}

    held = cast(
        HeldTentativeEvent,
        await tools["create_from_extract"].callable_ref(
            CreateFromExtractArgs(extract=_extract(raw_ref="m7:0"), event_type="flight")
        ),
    )
    listed = cast(
        HeldTentativeEventList,
        await tools["list_held_events"].callable_ref(ListHeldEventsArgs(status="held")),
    )
    discarded = cast(
        HeldTentativeEvent,
        await tools["discard_held_event"].callable_ref(HeldEventIdArgs(held_id=held.id)),
    )

    assert listed.events == [held]
    assert discarded.status is HeldEventStatus.DISCARDED
    assert client.write_calls["create_event"] == []
    assert staging.staged == []
