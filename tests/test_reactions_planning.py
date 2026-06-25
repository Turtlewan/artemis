from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest
from pydantic import BaseModel

from artemis.memory import EntityRef
from artemis.memory.trips import Trip, TripLeg, TripLegKind, TripStatus
from artemis.modules.productivity.tools import TaskScheduleArgs, TaskScheduleResult
from artemis.modules.travel import maps
from artemis.modules.travel.maps import Duration, MapsConnector
from artemis.ports.types import Vector
from artemis.reactions.emit import DomainEvent, EventType
from artemis.reactions.recipes import register_planning_reactions
from artemis.reactions.recipes.planning import (
    ReactionArgs,
    ReactionResult,
    react_task_complete_clear_block,
    react_task_deadline_to_block,
    react_task_done_mark_paid,
    react_trip_assembled_block,
)
from artemis.reactions.rulestore import TIER_A_BUILTINS, ReactionRule, ReactionTier
from artemis.registry import ToolRegistry
from artemis.runtime_config import RuntimeConfig


class OkResult(BaseModel):
    ok: bool = True


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 2

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        del query
        return [1.0, 0.0]


class FakeScheduleTaskFn:
    def __init__(self, *, event_id: str | None = "evt-1") -> None:
        self.event_id = event_id
        self.calls: list[TaskScheduleArgs] = []
        self.by_task: dict[str, str] = {}

    async def __call__(self, args: TaskScheduleArgs) -> TaskScheduleResult:
        self.calls.append(args)
        if self.event_id is None:
            event_id = None
        else:
            event_id = self.by_task.setdefault(args.task_id, self.event_id)
        return TaskScheduleResult(
            task_id=args.task_id,
            event_id=event_id,
            scheduled_block=args.window_start,
            message="scheduled" if event_id is not None else "no slot",
        )


class FakeClearLinkFn:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delete_calls: list[str] = []

    def __call__(self, task_id: str) -> None:
        if task_id not in self.calls:
            self.calls.append(task_id)


class FakeMarkBillPaidFn:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.store_writes: list[str] = []
        self.paid: set[str] = set()

    async def __call__(self, bill_id: str) -> OkResult:
        if bill_id not in self.paid:
            self.calls.append(bill_id)
            self.paid.add(bill_id)
        return OkResult()


class FakeTripAssembler:
    def __init__(self, trip: Trip) -> None:
        self.trip = trip

    def get_trip(self, id: str) -> Trip | None:
        return self.trip if self.trip.id == id else None


class FailingMaps:
    async def travel_time(
        self,
        origin: str,
        dest: str,
        *,
        mode: str = "driving",
        depart_at: str | None = None,
    ) -> Duration:
        del origin, dest, mode, depart_at
        raise RuntimeError("no maps key")


class FakeDispatcher:
    def __init__(self) -> None:
        self.ledger: set[str] = set()

    async def fire(
        self,
        rule: ReactionRule,
        event: DomainEvent,
        fn: FakeScheduleTaskFn | FakeClearLinkFn | FakeMarkBillPaidFn,
    ) -> None:
        key = _stable_key(rule, event)
        if key in self.ledger:
            return
        self.ledger.add(key)
        if rule.name == "task_block_create":
            await react_task_deadline_to_block(event, schedule_task_fn=cast(FakeScheduleTaskFn, fn))
        elif rule.name == "task_block_clear":
            await react_task_complete_clear_block(event, clear_link_fn=cast(FakeClearLinkFn, fn))
        elif rule.name == "task_done_mark_paid":
            await react_task_done_mark_paid(event, mark_bill_paid_fn=cast(FakeMarkBillPaidFn, fn))


async def test_c1_block_on_deadline_and_no_slot_degrade() -> None:
    schedule = FakeScheduleTaskFn(event_id="evt-1")

    result = await react_task_deadline_to_block(
        _task_created(due_at=True), schedule_task_fn=schedule
    )

    assert result.status == "linked"
    assert result.ref == "evt-1"
    assert result.undoable is True
    assert [call.task_id for call in schedule.calls] == ["t1"]

    skipped = await react_task_deadline_to_block(
        _task_created(due_at=False),
        schedule_task_fn=schedule,
    )
    assert skipped.status == "skipped"
    assert len(schedule.calls) == 1

    no_slot = FakeScheduleTaskFn(event_id=None)
    no_slot_result = await react_task_deadline_to_block(
        _task_created(due_at=True),
        schedule_task_fn=no_slot,
    )
    assert no_slot_result.status == "no_slot"
    assert no_slot_result.ref is None


async def test_c1_refire_is_deduped_by_rule_key() -> None:
    rule = _builtin("task_block_create")
    schedule = FakeScheduleTaskFn()
    dispatcher = FakeDispatcher()
    event = _task_created(due_at=True)

    await dispatcher.fire(rule, event, schedule)
    await dispatcher.fire(rule, event, schedule)

    assert len(schedule.calls) == 1


async def test_c4_clear_on_complete_bidirectional_and_no_delete() -> None:
    clear = FakeClearLinkFn()

    result = await react_task_complete_clear_block(
        _task_done(linked_event=True), clear_link_fn=clear
    )

    assert result.status == "cleared"
    assert result.ref == "t1"
    assert clear.calls == ["t1"]
    assert clear.delete_calls == []

    skipped = await react_task_complete_clear_block(
        _task_done(linked_event=False),
        clear_link_fn=clear,
    )
    assert skipped.status == "skipped"
    assert clear.calls == ["t1"]

    rule = _builtin("task_block_clear")
    dispatcher = FakeDispatcher()
    await dispatcher.fire(rule, _task_done(linked_event=True), clear)
    await dispatcher.fire(rule, _task_done(linked_event=True), clear)
    assert clear.calls == ["t1"]


async def test_c1_c4_round_trip() -> None:
    schedule = FakeScheduleTaskFn(event_id="evt-1")
    clear = FakeClearLinkFn()

    linked = await react_task_deadline_to_block(
        _task_created(due_at=True), schedule_task_fn=schedule
    )
    cleared = await react_task_complete_clear_block(
        _task_done(linked_event=True), clear_link_fn=clear
    )

    assert linked.status == "linked"
    assert cleared.status == "cleared"
    assert schedule.calls[0].task_id == "t1"
    assert clear.calls == ["t1"]


async def test_c2_mark_paid_uses_tool_and_noops_on_paid_bill() -> None:
    mark_paid = FakeMarkBillPaidFn()

    result = await react_task_done_mark_paid(_task_done(bill_ref=True), mark_bill_paid_fn=mark_paid)
    skipped = await react_task_done_mark_paid(
        _task_done(bill_ref=False),
        mark_bill_paid_fn=mark_paid,
    )
    await react_task_done_mark_paid(_task_done(bill_ref=True), mark_bill_paid_fn=mark_paid)

    assert result.status == "bill_paid"
    assert result.ref == "b1"
    assert result.undoable is True
    assert skipped.status == "skipped"
    assert mark_paid.calls == ["b1"]
    assert mark_paid.store_writes == []


async def test_trip_block_uses_fixed_buffer_and_refire_updates_one_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(maps, "get_runtime_config", RuntimeConfig)
    schedule = FakeScheduleTaskFn(event_id="evt-trip")
    trip = _trip()
    assembler = FakeTripAssembler(trip)
    event = _trip_assembled()

    result = await react_trip_assembled_block(
        event,
        schedule_task_fn=schedule,
        trip_assembler=assembler,
        maps=cast(MapsConnector, FailingMaps()),
    )
    second = await react_trip_assembled_block(
        event,
        schedule_task_fn=schedule,
        trip_assembler=assembler,
        maps=cast(MapsConnector, FailingMaps()),
    )

    assert result.status == "block_created"
    assert result.ref == "evt-trip"
    assert second.ref == "evt-trip"
    assert {call.task_id for call in schedule.calls} == {"trip:trip1:airport_leave"}
    assert schedule.calls[0].window_start == "2026-07-01T07:00:00+00:00"
    assert schedule.calls[0].window_end == "2026-07-01T10:00:00+00:00"


async def test_register_planning_reactions_rules_and_registry() -> None:
    registry = ToolRegistry(FakeEmbedder())
    rules = register_planning_reactions(
        registry,
        schedule_task_fn=FakeScheduleTaskFn(),
        clear_link_fn=FakeClearLinkFn(),
        mark_bill_paid_fn=FakeMarkBillPaidFn(),
        trip_assembler=FakeTripAssembler(_trip()),
        maps=None,
    )

    assert len(rules) == 4
    by_name = {rule.name: rule for rule in rules}
    for name in ("task_block_create", "task_block_clear", "task_done_mark_paid"):
        assert by_name[name] == _builtin(name)
        assert by_name[name].tier is ReactionTier.A
        assert by_name[name].external_effect is False
        assert isinstance(by_name[name].reaction_ref, str)

    trip_rule = by_name["trip_airport_block"]
    assert trip_rule.event_type is EventType.TRIP_ASSEMBLED
    assert trip_rule.tier is ReactionTier.B
    assert trip_rule.external_effect is False
    assert trip_rule.reaction_ref == "reaction:trip_airport_block"
    assert trip_rule.dedup_key_fields == ("trip_id",)
    assert trip_rule.stateful is True

    for rule in rules:
        assert registry.get_tool(rule.reaction_ref).callable_ref is not None

    task_tool = registry.get_tool("tasks.schedule")
    linked = cast(
        ReactionResult,
        await task_tool.callable_ref(
            ReactionArgs(
                event_type=EventType.TASK_CREATED.value,
                source_module="tasks",
                occurred_at="2026-06-25T00:00:00+00:00",
                dedup_key="task-created:t1",
                task_id="t1",
                due_at="2026-06-30T00:00:00+00:00",
            )
        ),
    )
    assert linked.status == "linked"


def test_import_reexport() -> None:
    from artemis.reactions.recipes import register_planning_reactions as imported

    assert imported is register_planning_reactions


def _task_created(*, due_at: bool) -> DomainEvent:
    payload: dict[str, str | int | float | bool] = {"task_id": "t1"}
    if due_at:
        payload["due_at"] = "2026-06-30T00:00:00+00:00"
    return DomainEvent(
        event_type=EventType.TASK_CREATED,
        source_module="tasks",
        entity_refs=(EntityRef(module="tasks", entity_id="t1"),),
        payload=payload,
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key="task-created:t1",
    )


def _task_done(*, linked_event: bool = True, bill_ref: bool = False) -> DomainEvent:
    payload: dict[str, str | int | float | bool] = {"task_id": "t1"}
    if linked_event:
        payload["linked_event_id"] = "evt-1"
    if bill_ref:
        payload["linked_bill_ref"] = "finance:bill:b1"
    return DomainEvent(
        event_type=EventType.TASK_DONE,
        source_module="tasks",
        entity_refs=(EntityRef(module="tasks", entity_id="t1"),),
        payload=payload,
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key="task-done:t1",
    )


def _trip_assembled() -> DomainEvent:
    return DomainEvent(
        event_type=EventType.TRIP_ASSEMBLED,
        source_module="travel",
        entity_refs=(EntityRef(module="memory", entity_id="trip:trip1"),),
        payload={
            "trip_id": "trip1",
            "destination_place_id": "place-dest",
            "start_dt": "2026-07-01T10:00:00+00:00",
            "end_dt": "2026-07-05T10:00:00+00:00",
            "leg_count": 1,
        },
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key="trip-assembled:trip1",
    )


def _trip() -> Trip:
    return Trip(
        id="trip1",
        name="Trip",
        status=TripStatus.PLANNED,
        destination_place_id="place-dest",
        start_dt="2026-07-01T10:00:00+00:00",
        end_dt="2026-07-05T10:00:00+00:00",
        traveller_entity_ids=(),
        legs=(
            TripLeg(
                id="leg1",
                trip_id="trip1",
                kind=TripLegKind.FLIGHT,
                title="Flight",
                start_dt="2026-07-01T10:00:00+00:00",
                end_dt="2026-07-01T14:00:00+00:00",
                origin_place_id="airport-origin",
                destination_place_id="airport-dest",
                confirmation_ref="ABC123",
                raw_ref="raw1",
            ),
        ),
    )


def _builtin(name: str) -> ReactionRule:
    for rule in TIER_A_BUILTINS:
        if rule.name == name:
            return rule
    raise AssertionError(name)


def _stable_key(rule: ReactionRule, event: DomainEvent) -> str:
    parts = [rule.name]
    for field in rule.dedup_key_fields:
        value = event.dedup_key if field == "dedup_key" else event.payload.get(field)
        parts.append(str(value or ""))
    parts.append(event.dedup_key)
    return ":".join(parts)
