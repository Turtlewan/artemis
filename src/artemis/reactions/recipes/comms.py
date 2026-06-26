"""Comms-cluster reaction recipes.

A4 routes commitment-looking email into the inert CaptureService suggestion
inbox. A5/A7 convert flight and meeting email extracts into held tentative
calendar events; flight extracts also pass through the Trip assembler so the
planning cluster owns the downstream airport-leave block. These reactions route
only on cheap email-ingested flags, then fetch the laundered structured extract
via ``source_ref`` before reading content.

The gift-signal recipe is registered here and writes a general-tagged module
fact through ``MemoryWritePath.add_module_fact`` (ADR-032 Decision 6).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec, UiSurface
from artemis.memory import EntityRef, TripExtract, TripLegKind
from artemis.memory.write_path import MemoryWritePath
from artemis.modules.calendar.create_from_extract import EventExtract, HeldTentativeEvent
from artemis.modules.gmail.structured import StructuredEmailExtract
from artemis.reactions.emit import DomainEvent, EventType
from artemis.reactions.rulestore import ReactionRule, ReactionTier
from artemis.registry import ToolRegistry

_EMAIL_TO_TASK_REF = "reaction:email_to_task"
_EMAIL_TO_HELD_EVENT_REF = "reaction:email_to_held_event"
_GIFT_SIGNAL_REF = "reaction:gift_signal"
_SOURCE_REF_RE = re.compile(r"^gmail:[A-Za-z0-9_-]+$")


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


CalendarFromExtractFn = Callable[[EventExtract, str], Awaitable[HeldTentativeEvent]]
FetchExtractFn = Callable[[str], Awaitable[StructuredEmailExtract | None]]


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
    fetch_extract: FetchExtractFn,
) -> ReactionResult:
    """A4 Tier-B: email commitment flag -> inert task suggestion.

    The live Gmail pre-flight stores only routing flags and a claim-check
    ``source_ref`` on the event args; content comes from the structured extract
    store.
    """
    if event.event_type is not EventType.EMAIL_INGESTED or not _payload_bool(
        event, "has_commitment"
    ):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    source_ref = _payload_str(event, "source_ref")
    if not _valid_source_ref(source_ref):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    assert source_ref is not None
    structured = await fetch_extract(source_ref)
    if structured is None or not structured.summary:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    suggestion_id = await capture_service.suggest_from_text(
        "email",
        structured.summary,
        untrusted=True,
    )
    return ReactionResult(status="suggested", ref=suggestion_id, undoable=False)


async def react_email_to_held_event(
    event: DomainEvent,
    *,
    calendar_from_extract_fn: CalendarFromExtractFn,
    trip_assembler: TripAssemblerLike,
    fetch_extract: FetchExtractFn,
) -> ReactionResult:
    """A5/A7 Tier-B: flight/meeting email -> held tentative calendar event.

    Flights first assemble or revise a Trip. The planning recipe reacts to the
    assembler's ``TRIP_ASSEMBLED`` emit and owns any airport-leave block; this
    recipe never calls Maps and never writes to Google.
    """
    if event.event_type is not EventType.EMAIL_INGESTED or not _payload_bool(event, "has_event"):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    source_ref = _payload_str(event, "source_ref")
    if not _valid_source_ref(source_ref):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    assert source_ref is not None
    structured = await fetch_extract(source_ref)
    if structured is None or structured.event_kind not in {"flight", "meeting"}:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    extract = _event_extract_from_structured(structured)
    if extract is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    if structured.event_kind == "flight":
        trip_assembler.assemble(_trip_extract_from_structured(structured, extract))

    held = await calendar_from_extract_fn(extract, structured.event_kind)
    return ReactionResult(status="held", ref=held.id, undoable=True)


async def react_gift_signal(
    event: DomainEvent,
    *,
    memory: MemoryWritePath,
    fetch_extract: FetchExtractFn,
) -> ReactionResult:
    """Tier-B: email gift signal -> general-tagged module memory fact."""
    if event.event_type is not EventType.EMAIL_INGESTED or not _payload_bool(
        event, "has_gift_signal"
    ):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    source_ref = _payload_str(event, "source_ref")
    if not _valid_source_ref(source_ref):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    assert source_ref is not None
    structured = await fetch_extract(source_ref)
    if structured is None or not structured.gift_item or not structured.gift_recipient:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    fact_id = await memory.add_module_fact(
        subject=structured.gift_recipient,
        relation="interested_in",
        object_=structured.gift_item,
        category="gift_signal",
        source_ref=source_ref,
        sensitivity="general",
    )
    return ReactionResult(status="noted", ref=fact_id, undoable=True)


async def _missing_fetch_extract(source_ref: str) -> StructuredEmailExtract | None:
    # Fail loud on misconfiguration: a silent None would make every comms reaction
    # skip every event with no diagnostic (R6c cross-model review).
    del source_ref
    raise RuntimeError("fetch_extract is required for comms reactions")


class _MissingMemory:
    """Lazy sentinel: a gift_signal fired without a wired memory write path raises a
    clear error on use instead of an AttributeError on None (R6c cross-model review).
    Registration still succeeds, so compositions that never fire a gift are unaffected."""

    async def add_module_fact(self, **_kwargs: object) -> str:
        raise RuntimeError("memory is required for the gift_signal reaction")


def register_comms_reactions(
    registry: ToolRegistry,
    *,
    capture_service: CaptureServiceLike,
    calendar_from_extract_fn: CalendarFromExtractFn,
    trip_assembler: TripAssemblerLike,
    fetch_extract: FetchExtractFn = _missing_fetch_extract,
    memory: object | None = None,
) -> tuple[ReactionRule, ...]:
    """Register built comms reaction tools and return rule bindings.

    Event map and idempotency keys:
    ``email-ingested/message_id`` -> A4 ``reaction:email_to_task`` and A5/A7
    ``reaction:email_to_held_event``. Legacy commitment-detection pushes migrate
    to A4 because graduation/observability matter; simple urgency notifiers stay
    as dumb Gmail hooks. Gift-signal writes a general-tagged fact through the
    module memory write path.
    """
    mem = cast(MemoryWritePath, memory if memory is not None else _MissingMemory())

    task_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(
            _email_to_task_tool,
            capture_service=capture_service,
            fetch_extract=fetch_extract,
        ),
    )
    held_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(
            _email_to_held_event_tool,
            calendar_from_extract_fn=calendar_from_extract_fn,
            trip_assembler=trip_assembler,
            fetch_extract=fetch_extract,
        ),
    )
    gift_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(_gift_signal_tool, memory=mem, fetch_extract=fetch_extract),
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
    _register_tool(
        registry,
        _GIFT_SIGNAL_REF,
        "Comms email gift signal to general-tagged memory fact.",
        gift_callable,
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
        ReactionRule(
            name=_GIFT_SIGNAL_REF,
            event_type=EventType.EMAIL_INGESTED,
            tier=ReactionTier.B,
            external_effect=False,
            reaction_ref=_GIFT_SIGNAL_REF,
            dedup_key_fields=("message_id",),
        ),
    )


async def _email_to_task_tool(
    args: ReactionArgs,
    *,
    capture_service: CaptureServiceLike,
    fetch_extract: FetchExtractFn,
) -> ReactionResult:
    return await react_commitment_to_task(
        _event_from_args(args),
        capture_service=capture_service,
        fetch_extract=fetch_extract,
    )


async def _email_to_held_event_tool(
    args: ReactionArgs,
    *,
    calendar_from_extract_fn: CalendarFromExtractFn,
    trip_assembler: TripAssemblerLike,
    fetch_extract: FetchExtractFn,
) -> ReactionResult:
    return await react_email_to_held_event(
        _event_from_args(args),
        calendar_from_extract_fn=calendar_from_extract_fn,
        trip_assembler=trip_assembler,
        fetch_extract=fetch_extract,
    )


async def _gift_signal_tool(
    args: ReactionArgs,
    *,
    memory: MemoryWritePath,
    fetch_extract: FetchExtractFn,
) -> ReactionResult:
    return await react_gift_signal(
        _event_from_args(args),
        memory=memory,
        fetch_extract=fetch_extract,
    )


def _event_extract_from_structured(structured: StructuredEmailExtract) -> EventExtract | None:
    if (
        not structured.summary
        or structured.start_datetime is None
        or structured.end_datetime is None
    ):
        return None
    return EventExtract(
        summary=structured.summary,
        start_datetime=structured.start_datetime,
        end_datetime=structured.end_datetime,
        location=structured.location,
        description=structured.description,
        attendee_emails=structured.attendee_emails,
        raw_ref=structured.source_ref,
    )


def _trip_extract_from_structured(
    structured: StructuredEmailExtract, extract: EventExtract
) -> TripExtract:
    return TripExtract(
        kind=TripLegKind.FLIGHT,
        title=structured.title or extract.summary,
        start_dt=extract.start_datetime,
        end_dt=extract.end_datetime,
        origin=structured.origin,
        destination=structured.destination,
        confirmation_ref=structured.confirmation_ref,
        co_travellers=structured.co_travellers,
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


def _valid_source_ref(s: str | None) -> bool:
    return s is not None and _SOURCE_REF_RE.match(s) is not None
