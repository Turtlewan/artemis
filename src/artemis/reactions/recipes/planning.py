"""Planning-cluster reaction recipes.

C1/C4 are the Decision-8 Task<->Calendar pair: C1 links a deadlined task to a
self-only focus block, and C4 clears the task link on completion without deleting
the Google event. C2 marks explicitly linked bills paid through the finance tool
handle, never the finance store. The Trip airport block is Tier-B because its
travel estimate is useful but uncertain; it is stateful so revised trips update
one owned block instead of duplicating it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec, UiSurface
from artemis.memory import EntityRef
from artemis.memory.trips import Trip, TripLeg, TripLegKind
from artemis.modules.productivity.tools import TaskScheduleArgs, TaskScheduleResult
from artemis.modules.travel.maps import MapsConnector, RouteClass, travel_time_or_buffer
from artemis.reactions.emit import DomainEvent, EventType
from artemis.reactions.rulestore import TIER_A_BUILTINS, ReactionRule, ReactionTier
from artemis.registry import ToolRegistry

ScheduleTaskFn = Callable[[TaskScheduleArgs], Awaitable[TaskScheduleResult]]
ClearLinkFn = Callable[[str], None]
MarkBillPaidFn = Callable[[str], Awaitable[BaseModel]]

_TASKS_SCHEDULE_REF = "tasks.schedule"
_FINANCE_MARK_PAID_REF = "finance.mark_bill_paid"
_TRIP_AIRPORT_BLOCK_REF = "reaction:trip_airport_block"


class ReactionResult(BaseModel):
    """Result returned by internal reaction recipes."""

    model_config = ConfigDict(frozen=True)

    status: str
    ref: str | None = None
    undoable: bool


class ReactionArgs(BaseModel):
    """Dispatcher-provided scalar event args for recipe tool wrappers."""

    model_config = ConfigDict(extra="allow")

    event_type: str
    source_module: str
    occurred_at: str
    dedup_key: str
    entity_refs: list[dict[str, str]] = []


class TripLookup(Protocol):
    """Trip lookup handle exposed by the Trip repository/assembler seam."""

    def get_trip(self, id: str) -> Trip | None:
        """Return an assembled trip."""
        ...


async def react_task_deadline_to_block(
    event: DomainEvent,
    *,
    schedule_task_fn: ScheduleTaskFn,
) -> ReactionResult:
    """C1 Tier-A: task-created with due_at -> self-only task focus block."""
    task_id = _payload_str(event, "task_id")
    if task_id is None or _payload_str(event, "due_at") is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    result = await schedule_task_fn(TaskScheduleArgs(task_id=task_id))
    if result.event_id is None:
        return ReactionResult(status="no_slot", ref=None, undoable=False)
    return ReactionResult(status="linked", ref=result.event_id, undoable=True)


async def react_task_complete_clear_block(
    event: DomainEvent,
    *,
    clear_link_fn: ClearLinkFn,
) -> ReactionResult:
    """C4 Tier-A: task-done with a linked event clears only the Task link."""
    task_id = _payload_str(event, "task_id")
    if task_id is None or _payload_str(event, "linked_event_id") is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    clear_link_fn(task_id)
    return ReactionResult(status="cleared", ref=task_id, undoable=False)


async def react_task_done_mark_paid(
    event: DomainEvent,
    *,
    mark_bill_paid_fn: MarkBillPaidFn,
) -> ReactionResult:
    """C2 Tier-A extended: task-done with finance:bill:<id> marks the bill paid."""
    bill_ref = _payload_str(event, "linked_bill_ref")
    if bill_ref is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    bill_id = _bill_id_from_ref(bill_ref)
    if bill_id is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    await mark_bill_paid_fn(bill_id)
    return ReactionResult(status="bill_paid", ref=bill_id, undoable=True)


async def react_trip_assembled_block(
    event: DomainEvent,
    *,
    schedule_task_fn: ScheduleTaskFn,
    trip_assembler: TripLookup,
    maps: MapsConnector | None,
) -> ReactionResult:
    """Tier-B: trip-assembled -> owned airport-leave focus block."""
    trip_id = _payload_str(event, "trip_id")
    if trip_id is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    trip = trip_assembler.get_trip(trip_id)
    if trip is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    flight = _first_departing_flight(trip)
    if flight is None or flight.start_dt is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    destination = flight.origin_place_id or trip.destination_place_id or "airport"
    duration = await travel_time_or_buffer(
        maps,
        "home",
        destination,
        route_class=RouteClass.INTERNATIONAL,
        mode="driving",
        depart_at=flight.start_dt,
    )
    leave_at = _minus_minutes(flight.start_dt, duration.minutes)
    result = await schedule_task_fn(
        TaskScheduleArgs(
            task_id=f"trip:{trip_id}:airport_leave",
            window_start=leave_at,
            window_end=flight.start_dt,
        )
    )
    if result.event_id is None:
        return ReactionResult(status="no_slot", ref=None, undoable=False)
    return ReactionResult(status="block_created", ref=result.event_id, undoable=True)


def register_planning_reactions(
    registry: ToolRegistry,
    *,
    schedule_task_fn: ScheduleTaskFn,
    clear_link_fn: ClearLinkFn,
    mark_bill_paid_fn: MarkBillPaidFn,
    trip_assembler: TripLookup,
    maps: MapsConnector | None,
) -> tuple[ReactionRule, ...]:
    """Register Planning reaction tools and return their rule bindings.

    Event map and idempotency keys:
    task-created/task_id -> C1 task_block_create; task-done/task_id -> C4
    task_block_clear and C2 task_done_mark_paid; trip-assembled/trip_id ->
    Tier-B trip_airport_block. C1 and C4 are the two halves of the always-linked
    Task<->Calendar invariant.
    """

    async def task_schedule_recipe(args: ReactionArgs) -> ReactionResult:
        event = _event_from_args(args)
        if event.event_type is EventType.TASK_DONE:
            return await react_task_complete_clear_block(event, clear_link_fn=clear_link_fn)
        return await react_task_deadline_to_block(event, schedule_task_fn=schedule_task_fn)

    async def finance_mark_paid_recipe(args: ReactionArgs) -> ReactionResult:
        return await react_task_done_mark_paid(
            _event_from_args(args),
            mark_bill_paid_fn=mark_bill_paid_fn,
        )

    async def trip_airport_block_recipe(args: ReactionArgs) -> ReactionResult:
        return await react_trip_assembled_block(
            _event_from_args(args),
            schedule_task_fn=schedule_task_fn,
            trip_assembler=trip_assembler,
            maps=maps,
        )

    _register_tool(
        registry,
        _TASKS_SCHEDULE_REF,
        "Planning C1/C4 Task<->Calendar link recipe.",
        task_schedule_recipe,
    )
    _register_tool(
        registry,
        _FINANCE_MARK_PAID_REF,
        "Planning C2 task-done to mark-paid recipe.",
        finance_mark_paid_recipe,
    )
    _register_tool(
        registry,
        _TRIP_AIRPORT_BLOCK_REF,
        "Planning Tier-B trip airport-leave block recipe.",
        trip_airport_block_recipe,
    )

    return (
        _builtin("task_block_create"),
        _builtin("task_block_clear"),
        _builtin("task_done_mark_paid"),
        ReactionRule(
            name="trip_airport_block",
            event_type=EventType.TRIP_ASSEMBLED,
            tier=ReactionTier.B,
            external_effect=False,
            reaction_ref=_TRIP_AIRPORT_BLOCK_REF,
            dedup_key_fields=("trip_id",),
            stateful=True,
        ),
    )


def _register_tool(
    registry: ToolRegistry,
    fq_ref: str,
    description: str,
    callable_ref: Callable[[ReactionArgs], Awaitable[ReactionResult]],
) -> None:
    module_name, tool_name = _split_ref(fq_ref)
    tool = ToolSpec(
        name=tool_name,
        description=description,
        args_schema=ReactionArgs,
        return_schema=ReactionResult,
        callable_ref=callable_ref,
        action_risk=ActionRisk.WRITE,
    )
    registry._tools[fq_ref] = tool
    registry._pending.append((fq_ref, tool))
    if module_name not in registry._manifests and ":" not in module_name:
        registry._manifests[module_name] = ModuleManifest(
            name=module_name,
            version="0.1.0",
            description=f"Reaction recipe tools for {module_name}.",
            tools=[],
            data_scope=DataScope.OWNER_PRIVATE,
            permissions=Permissions(owner=True, guest=False),
            proactive_hooks=[],
            ui=UiSurface(kind="none"),
        )


def _split_ref(fq_ref: str) -> tuple[str, str]:
    if ":" in fq_ref and "." not in fq_ref:
        module, tool = fq_ref.split(":", 1)
        return module, tool
    module, tool = fq_ref.split(".", 1)
    return module, tool


def _builtin(name: str) -> ReactionRule:
    for rule in TIER_A_BUILTINS:
        if rule.name == name:
            return rule
    raise KeyError(name)


def _event_from_args(args: ReactionArgs) -> DomainEvent:
    dumped = args.model_dump()
    payload = {
        key: value
        for key, value in dumped.items()
        if key
        not in {
            "event_type",
            "source_module",
            "occurred_at",
            "dedup_key",
            "entity_refs",
        }
        and isinstance(value, (str, int, float, bool))
    }
    refs = tuple(
        EntityRef(module=ref["module"], entity_id=ref["entity_id"])
        for ref in args.entity_refs
        if "module" in ref and "entity_id" in ref
    )
    return DomainEvent(
        event_type=EventType(args.event_type),
        source_module=args.source_module,
        entity_refs=refs,
        payload=payload,
        occurred_at=args.occurred_at,
        dedup_key=args.dedup_key,
    )


def _payload_str(event: DomainEvent, key: str) -> str | None:
    value = event.payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _bill_id_from_ref(ref: str) -> str | None:
    prefix = "finance:bill:"
    if not ref.startswith(prefix):
        return None
    bill_id = ref.removeprefix(prefix)
    return bill_id or None


def _first_departing_flight(trip: Trip) -> TripLeg | None:
    flights = [
        leg for leg in trip.legs if leg.kind is TripLegKind.FLIGHT and leg.start_dt is not None
    ]
    return min(flights, key=lambda leg: leg.start_dt or "") if flights else None


def _minus_minutes(value: str, minutes: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed - timedelta(minutes=minutes)).isoformat()
