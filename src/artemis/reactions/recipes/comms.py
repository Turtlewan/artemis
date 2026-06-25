"""Comms-cluster reaction recipes.

A4 routes commitment-looking email into the inert CaptureService suggestion
inbox. A5/A7 convert flight and meeting email extracts into held tentative
calendar events; flight extracts also pass through the Trip assembler so the
planning cluster owns the downstream airport-leave block. Both rules bind to
``email-ingested`` and use ``message_id`` as the dispatcher idempotency field.

The gift-signal recipe is intentionally not registered here yet: the live
memory store still exposes the older person-scoped ``add_fact(person_id, fact)``
port, not the ADR-021 module-initiated ``add_fact(source_kind, source_ref, ...)``
path required for ``reaction:gift_signal``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec, UiSurface
from artemis.memory import EntityRef, TripExtract, TripLegKind
from artemis.modules.calendar.create_from_extract import EventExtract, HeldTentativeEvent
from artemis.reactions.emit import DomainEvent, EventType
from artemis.reactions.rulestore import ReactionRule, ReactionTier
from artemis.registry import ToolRegistry

_EMAIL_TO_TASK_REF = "reaction:email_to_task"
_EMAIL_TO_HELD_EVENT_REF = "reaction:email_to_held_event"


class CaptureServiceLike(Protocol):
    """CaptureService surface used by A4."""

    async def suggest_from_text(self, source: str, text: str, *, untrusted: bool) -> str | None:
        """Create an inert suggestion from sanitized email summary text."""
        ...


class TripAssemblerLike(Protocol):
    """TripAssembler surface used by A5."""

    def assemble(self, extract: TripExtract) -> str:
        """Assemble or revise a trip from one sanitized itinerary leg."""
        ...


CalendarFromExtractFn = Callable[[EventExtract], Awaitable[HeldTentativeEvent]]


class ReactionResult(BaseModel):
    """Result returned by internal reaction recipes."""

    model_config = ConfigDict(frozen=True)

    status: str
    ref: str | None = None
    undoable: bool


class ReactionArgs(BaseModel):
    """Dispatcher-provided scalar event args for comms recipe wrappers."""

    model_config = ConfigDict(extra="allow")

    event_type: str
    source_module: str
    occurred_at: str
    dedup_key: str
    entity_refs: list[dict[str, str]] = Field(default_factory=list)


async def react_commitment_to_task(
    event: DomainEvent,
    *,
    capture_service: CaptureServiceLike,
) -> ReactionResult:
    """A4 Tier-B: email commitment flag -> inert task suggestion.

    The live Gmail pre-flight stores only sanitized extract fields on the event
    args; raw email bodies are never accepted by this callable.
    """
    if event.event_type is not EventType.EMAIL_INGESTED or not _payload_bool(
        event, "commitment_detected"
    ):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    summary = _payload_str(event, "extract_summary")
    if summary is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    suggestion_id = await capture_service.suggest_from_text(
        "email",
        summary,
        untrusted=True,
    )
    return ReactionResult(status="suggested", ref=suggestion_id, undoable=False)


async def react_email_to_held_event(
    event: DomainEvent,
    *,
    calendar_from_extract_fn: Callable[[EventExtract, str], Awaitable[HeldTentativeEvent]],
    trip_assembler: TripAssemblerLike,
) -> ReactionResult:
    """A5/A7 Tier-B: flight/meeting email -> held tentative calendar event.

    Flights first assemble or revise a Trip. The planning recipe reacts to the
    assembler's ``TRIP_ASSEMBLED`` emit and owns any airport-leave block; this
    recipe never calls Maps and never writes to Google.
    """
    if event.event_type is not EventType.EMAIL_INGESTED:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    event_kind = _payload_str(event, "event_kind")
    if event_kind not in {"flight", "meeting"}:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    extract = _event_extract(event)
    if extract is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    if event_kind == "flight":
        trip_assembler.assemble(_trip_extract(event, extract))

    held = await calendar_from_extract_fn(extract, event_kind)
    return ReactionResult(status="held", ref=held.id, undoable=True)


def register_comms_reactions(
    registry: ToolRegistry,
    *,
    capture_service: CaptureServiceLike,
    calendar_from_extract_fn: Callable[[EventExtract, str], Awaitable[HeldTentativeEvent]],
    trip_assembler: TripAssemblerLike,
    memory: object | None = None,
) -> tuple[ReactionRule, ...]:
    """Register built comms reaction tools and return rule bindings.

    Event map and idempotency keys:
    ``email-ingested/message_id`` -> A4 ``reaction:email_to_task`` and A5/A7
    ``reaction:email_to_held_event``. Legacy commitment-detection pushes migrate
    to A4 because graduation/observability matter; simple urgency notifiers stay
    as dumb Gmail hooks. ``memory`` is accepted for the future gift-signal recipe
    but intentionally unused until the module fact-push prerequisite exists.
    """
    del memory

    task_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(_email_to_task_tool, capture_service=capture_service),
    )
    held_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(
            _email_to_held_event_tool,
            calendar_from_extract_fn=calendar_from_extract_fn,
            trip_assembler=trip_assembler,
        ),
    )
    _register_tool(
        registry,
        _EMAIL_TO_TASK_REF,
        "Comms A4 email commitment to inert task suggestion.",
        task_callable,
    )
    _register_tool(
        registry,
        _EMAIL_TO_HELD_EVENT_REF,
        "Comms A5/A7 email flight or meeting to held event.",
        held_callable,
    )

    return (
        ReactionRule(
            name=_EMAIL_TO_TASK_REF,
            event_type=EventType.EMAIL_INGESTED,
            tier=ReactionTier.B,
            external_effect=False,
            reaction_ref=_EMAIL_TO_TASK_REF,
            dedup_key_fields=("message_id",),
        ),
        ReactionRule(
            name=_EMAIL_TO_HELD_EVENT_REF,
            event_type=EventType.EMAIL_INGESTED,
            tier=ReactionTier.B,
            external_effect=False,
            reaction_ref=_EMAIL_TO_HELD_EVENT_REF,
            dedup_key_fields=("message_id",),
            stateful=True,
        ),
    )


async def _email_to_task_tool(
    args: ReactionArgs,
    *,
    capture_service: CaptureServiceLike,
) -> ReactionResult:
    return await react_commitment_to_task(
        _event_from_args(args),
        capture_service=capture_service,
    )


async def _email_to_held_event_tool(
    args: ReactionArgs,
    *,
    calendar_from_extract_fn: Callable[[EventExtract, str], Awaitable[HeldTentativeEvent]],
    trip_assembler: TripAssemblerLike,
) -> ReactionResult:
    return await react_email_to_held_event(
        _event_from_args(args),
        calendar_from_extract_fn=calendar_from_extract_fn,
        trip_assembler=trip_assembler,
    )


def _event_extract(event: DomainEvent) -> EventExtract | None:
    summary = _payload_str(event, "extract_summary")
    start = _payload_str(event, "start_datetime") or _payload_str(event, "start_dt")
    end = _payload_str(event, "end_datetime") or _payload_str(event, "end_dt")
    raw_ref = _raw_ref(event)
    if summary is None or start is None or end is None or raw_ref is None:
        return None
    return EventExtract(
        summary=summary,
        start_datetime=start,
        end_datetime=end,
        location=_payload_str(event, "location"),
        description=_payload_str(event, "description"),
        attendee_emails=_csv_tuple(_payload_str(event, "attendee_emails")),
        raw_ref=raw_ref,
    )


def _trip_extract(event: DomainEvent, extract: EventExtract) -> TripExtract:
    return TripExtract(
        kind=TripLegKind.FLIGHT,
        title=_payload_str(event, "title") or extract.summary,
        start_dt=extract.start_datetime,
        end_dt=extract.end_datetime,
        origin=_payload_str(event, "origin"),
        destination=_payload_str(event, "destination"),
        confirmation_ref=_payload_str(event, "confirmation_ref"),
        co_travellers=_csv_tuple(_payload_str(event, "co_travellers")),
        raw_ref=extract.raw_ref,
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


def _payload_bool(event: DomainEvent, key: str) -> bool:
    return event.payload.get(key) is True


def _raw_ref(event: DomainEvent) -> str | None:
    raw_ref = _payload_str(event, "raw_ref")
    if raw_ref is not None:
        return raw_ref
    message_id = _payload_str(event, "message_id")
    if message_id is None:
        return None
    return f"{message_id}:0"


def _csv_tuple(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())
