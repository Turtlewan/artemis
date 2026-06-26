from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic import BaseModel, ConfigDict

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import ActionRisk, ToolSpec
from artemis.modules.calendar.create_from_extract import (
    EventExtract,
    HeldEventStatus,
    HeldTentativeEvent,
)
from artemis.modules.productivity.capture import CaptureService
from artemis.modules.productivity.tools import TaskScheduleArgs, TaskScheduleResult
from artemis.ports.types import Vector
from artemis.reactions import compose as compose_module
from artemis.reactions import compose_reactions
from artemis.reactions.dispatcher import ReactionDispatcher
from artemis.reactions.emit import (
    DomainEvent,
    EventBus,
    EventType,
    depth_stamping_emit,
    reaction_depth,
)
from artemis.reactions.ledger import ReactionLedger
from artemis.reactions.recipes.self import BillTaskResult
from artemis.reactions.reconciler import MatchOutcome, MatchResult
from artemis.reactions.rulestore import ReactionRule, ReactionRuleStore, ReactionTier
from artemis.recipes import Promoter, RecipeStore
from artemis.registry import ToolRegistry
from artemis.runtime_config import ReactionConfig, RuntimeConfig
from artemis.staging.model import PendingAction
from artemis.staging.service import ActionStagingService


class ReactionArgs(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_type: str
    source_module: str
    occurred_at: str
    dedup_key: str
    entity_refs: list[dict[str, str]]


class ReactionResult(BaseModel):
    ok: bool = True


class FakeRuleStore:
    def __init__(self, rules: list[ReactionRule]) -> None:
        self._rules = rules
        self.lookups = 0

    def rules_for(self, event_type: EventType) -> list[ReactionRule]:
        self.lookups += 1
        return [rule for rule in self._rules if rule.event_type == event_type]


class FakeToolRegistry:
    def __init__(self) -> None:
        self.calls: dict[str, list[ReactionArgs]] = {}
        self.failures_remaining: dict[str, int] = {}
        self.emit: Callable[[DomainEvent], None] | None = None

    def get_tool(self, fq_name: str) -> ToolSpec:
        async def call(args: ReactionArgs) -> ReactionResult:
            self.calls.setdefault(fq_name, []).append(args)
            if self.emit is not None:
                self.emit(
                    DomainEvent(
                        event_type=EventType.BILL_PAID,
                        source_module="finance",
                        payload={"bill_id": "bill-1", "payee": "Acme"},
                        occurred_at="2026-06-25T00:00:00+00:00",
                        dedup_key="bill-paid:bill-1",
                    )
                )
            remaining = self.failures_remaining.get(fq_name, 0)
            if remaining > 0:
                self.failures_remaining[fq_name] = remaining - 1
                raise RuntimeError(f"boom: {fq_name}")
            return ReactionResult()

        callable_ref: Callable[[ReactionArgs], Awaitable[BaseModel]] = call
        return ToolSpec(
            name=fq_name.rsplit(".", 1)[-1],
            description=fq_name,
            args_schema=ReactionArgs,
            return_schema=ReactionResult,
            callable_ref=callable_ref,
            action_risk=ActionRisk.READ,
        )


class FakeActionStagingService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def stage(
        self,
        module: str,
        tool: str,
        args: dict[str, object],
        summary: str,
        *,
        ttl: object | None = None,
    ) -> PendingAction | None:
        self.calls.append(
            {"module": module, "tool": tool, "args": args, "summary": summary, "ttl": ttl}
        )
        return None


class FakeCaptureService:
    def __init__(self) -> None:
        self.suggestions: list[tuple[str, str, bool]] = []
        self.bill_tasks: list[str] = []

    async def suggest_from_text(
        self,
        source: Literal["chat", "email", "calendar"],
        text: str,
        *,
        untrusted: bool = False,
    ) -> str:
        self.suggestions.append((source, text, untrusted))
        return "suggestion-1"

    async def create_task_from_bill(
        self,
        *,
        bill_id: str,
        title: str,
        due_at: str,
        source: str,
    ) -> BillTaskResult:
        del title, due_at, source
        self.bill_tasks.append(bill_id)
        return BillTaskResult(task_id=f"task-{bill_id}")


class FakeRecipeStore:
    def list(self, *, status: object | None = None) -> list[object]:
        del status
        return []


class FakePromoter:
    async def note_occurrence(self, rule_name: str) -> None:
        del rule_name


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 1

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0] for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        del query
        return [1.0]


class FakeTripAssembler:
    def assemble(self, extract: object) -> str:
        del extract
        return "trip-1"

    def get_trip(self, id: str) -> None:
        del id
        return None


class FakeReconciler:
    def match(self, target: object, candidates: object) -> MatchResult:
        del target, candidates
        return MatchResult(
            outcome=MatchOutcome.NONE,
            target_id="target",
            matched_id=None,
            score=0.0,
            reason="none",
        )


@pytest.fixture
def ledger(tmp_path: Path) -> ReactionLedger:
    settings = Settings(data_root=tmp_path)
    key_provider = FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True)
    return ReactionLedger(settings, key_provider)


def _event(*, depth: int = 0, dedup_key: str = "event-1") -> DomainEvent:
    return DomainEvent(
        event_type=EventType.TXN_RECORDED,
        source_module="finance",
        payload={"txn_id": "txn-1", "amount": 12.5},
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key=dedup_key,
        depth=depth,
    )


def _task_done_event() -> DomainEvent:
    return DomainEvent(
        event_type=EventType.TASK_DONE,
        source_module="tasks",
        payload={"task_id": "task-1", "linked_event_id": "event-1"},
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key="task-done:task-1",
    )


def _rule(
    name: str = "rule",
    *,
    reaction_ref: str = "finance.mark_settlement",
    event_type: EventType = EventType.TXN_RECORDED,
    external_effect: bool = False,
) -> ReactionRule:
    return ReactionRule(
        name=name,
        event_type=event_type,
        tier=ReactionTier.A,
        external_effect=external_effect,
        reaction_ref=reaction_ref,
        dedup_key_fields=("txn_id",),
    )


def _dispatcher(
    *,
    bus: EventBus,
    rules: list[ReactionRule],
    ledger: ReactionLedger,
    registry: FakeToolRegistry | None = None,
    notices: list[str] | None = None,
    mode: Literal["observe", "live"] = "live",
    max_depth: int = 5,
    max_queue: int = 1000,
) -> tuple[ReactionDispatcher, FakeToolRegistry, FakeActionStagingService]:
    tool_registry = registry or FakeToolRegistry()
    staging = FakeActionStagingService()
    dispatcher = ReactionDispatcher(
        bus,
        cast(ReactionRuleStore, FakeRuleStore(rules)),
        ledger,
        cast(ToolRegistry, tool_registry),
        cast(ActionStagingService, staging),
        capture_service=cast(CaptureService, FakeCaptureService()),
        notice_sink=notices.append if notices is not None else None,
        mode=mode,
        max_depth=max_depth,
        max_queue=max_queue,
        logger=logging.getLogger("tests.reactions.compose"),
    )
    return dispatcher, tool_registry, staging


def test_config_defaults_and_validation() -> None:
    assert RuntimeConfig().reaction.reactions_mode == "observe"
    assert RuntimeConfig().reaction.max_reaction_depth == 5
    with pytest.raises(ValueError):
        ReactionConfig(reactions_mode="bogus")
    with pytest.raises(ValueError):
        ReactionConfig(max_reaction_depth=0)


def test_depth_stamping_emit_sets_child_depth() -> None:
    seen: list[DomainEvent] = []
    bus = EventBus()
    bus.subscribe(seen.append)

    event = _event()
    bus.emit(event)
    assert seen[-1].depth == 0

    token = reaction_depth.set(2)
    try:
        depth_stamping_emit(bus)(event)
    finally:
        reaction_depth.reset(token)

    assert seen[-1].depth == 3


def test_ledger_has_fired_and_prune(ledger: ReactionLedger) -> None:
    assert ledger.has_fired("r", "old") is False
    assert ledger.try_claim("r", "old", now="2026-01-01T00:00:00+00:00") is True
    assert ledger.try_claim("r", "new", now="2026-06-25T00:00:00+00:00") is True
    assert ledger.has_fired("r", "old") is True

    assert ledger.prune_older_than("2026-03-01T00:00:00+00:00") == 1
    assert ledger.has_fired("r", "old") is False
    assert ledger.has_fired("r", "new") is True


@pytest.mark.anyio
async def test_observe_gate_emits_would_without_ledger_or_effect(ledger: ReactionLedger) -> None:
    bus = EventBus()
    notices: list[str] = []
    dispatcher, registry, staging = _dispatcher(
        bus=bus,
        rules=[_rule("settle")],
        ledger=ledger,
        notices=notices,
        mode="observe",
    )

    bus.emit(_event())
    bus.emit(_event())
    assert await dispatcher.drain_once() == 2

    assert notices == ["WOULD execute: settle"]
    assert registry.calls == {}
    assert staging.calls == []
    assert ledger.has_fired("settle", "settle:txn-1:event-1") is False


@pytest.mark.anyio
async def test_live_executes_and_claims_after_success(ledger: ReactionLedger) -> None:
    bus = EventBus()
    notices: list[str] = []
    dispatcher, registry, _staging = _dispatcher(
        bus=bus,
        rules=[_rule("settle")],
        ledger=ledger,
        notices=notices,
    )

    bus.emit(_event())
    assert await dispatcher.drain_once() == 1

    assert len(registry.calls["finance.mark_settlement"]) == 1
    assert notices == ["Auto: settle fired (undoable)"]
    assert ledger.has_fired("settle", "settle:txn-1:event-1") is True


@pytest.mark.anyio
async def test_effect_then_claim_retries_after_handler_failure(ledger: ReactionLedger) -> None:
    bus = EventBus()
    registry = FakeToolRegistry()
    registry.failures_remaining["finance.mark_settlement"] = 1
    dispatcher, _registry, _staging = _dispatcher(
        bus=bus,
        rules=[_rule("settle")],
        ledger=ledger,
        registry=registry,
    )

    bus.emit(_event())
    assert await dispatcher.drain_once() == 1
    assert ledger.has_fired("settle", "settle:txn-1:event-1") is False

    bus.emit(_event())
    assert await dispatcher.drain_once() == 1
    assert len(registry.calls["finance.mark_settlement"]) == 2
    assert ledger.has_fired("settle", "settle:txn-1:event-1") is True


@pytest.mark.anyio
async def test_depth_guard_drops_and_handler_reemit_is_stamped(
    ledger: ReactionLedger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    rule_store = FakeRuleStore([_rule("settle")])
    dispatcher = ReactionDispatcher(
        bus,
        cast(ReactionRuleStore, rule_store),
        ledger,
        cast(ToolRegistry, FakeToolRegistry()),
        cast(ActionStagingService, FakeActionStagingService()),
        notice_sink=list[str]().append,
        mode="live",
        max_depth=2,
        logger=logging.getLogger("tests.reactions.compose.depth"),
    )

    with caplog.at_level(logging.WARNING):
        bus.emit(_event(depth=2))
        assert await dispatcher.drain_once() == 1

    assert rule_store.lookups == 0
    assert "reaction cascade depth 2 reached" in caplog.text

    seen: list[DomainEvent] = []
    bus = EventBus()
    bus.subscribe(seen.append)
    registry = FakeToolRegistry()
    registry.emit = depth_stamping_emit(bus)
    dispatcher, _registry, _staging = _dispatcher(
        bus=bus,
        rules=[_rule("emit_child", reaction_ref="self.emit_child")],
        ledger=ledger,
        registry=registry,
        max_depth=5,
    )

    bus.emit(_event(depth=1, dedup_key="parent"))
    assert await dispatcher.drain_once() == 2
    assert [event.depth for event in seen if event.event_type is EventType.BILL_PAID] == [2]


def test_bounded_queue_drop_does_not_raise(
    ledger: ReactionLedger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    _dispatcher(bus=bus, rules=[_rule("settle")], ledger=ledger, max_queue=1)

    with caplog.at_level(logging.WARNING):
        bus.emit(_event(dedup_key="one"))
        bus.emit(_event(dedup_key="two"))

    assert "reaction queue full; dropping" in caplog.text


@pytest.mark.anyio
async def test_ctor_guards(ledger: ReactionLedger) -> None:
    bus = EventBus()
    with pytest.raises(ValueError, match="notice_sink is required"):
        ReactionDispatcher(
            bus,
            cast(ReactionRuleStore, FakeRuleStore([])),
            ledger,
            cast(ToolRegistry, FakeToolRegistry()),
            cast(ActionStagingService, FakeActionStagingService()),
            mode="observe",
        )

    dispatcher, _registry, _staging = _dispatcher(bus=EventBus(), rules=[], ledger=ledger)
    task = dispatcher.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            dispatcher.start()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_compose_graph_registers_packs_and_worker_processes_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        compose_module,
        "get_runtime_config",
        lambda: RuntimeConfig(reaction=ReactionConfig(reactions_mode="live")),
    )
    settings = Settings(data_root=tmp_path)
    key_provider = FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True)
    registry = ToolRegistry(FakeEmbedder())
    clear_calls: list[str] = []

    async def calendar_from_extract(
        extract: EventExtract,
        event_type: str,
    ) -> HeldTentativeEvent:
        return HeldTentativeEvent(
            id="held-1",
            event_type=event_type,
            summary=extract.summary,
            start_datetime=extract.start_datetime,
            end_datetime=extract.end_datetime,
            location=extract.location,
            description=extract.description,
            attendee_emails=extract.attendee_emails,
            status=HeldEventStatus.HELD,
            raw_ref=extract.raw_ref,
            google_event_id=None,
            pending_action_id=None,
        )

    async def schedule_task(args: TaskScheduleArgs) -> TaskScheduleResult:
        return TaskScheduleResult(
            task_id=args.task_id,
            event_id="event-1",
            scheduled_block="2026-06-25T01:00:00+00:00",
            message="scheduled",
        )

    bus, dispatcher, worker = compose_reactions(
        recipe_store=cast(RecipeStore, FakeRecipeStore()),
        promoter=cast(Promoter, FakePromoter()),
        registry=registry,
        staging=cast(ActionStagingService, FakeActionStagingService()),
        capture_service=FakeCaptureService(),
        calendar_from_extract_fn=calendar_from_extract,
        trip_assembler=FakeTripAssembler(),
        get_linked_task_ref_fn=_none_linked_task_ref,
        fetch_extract=_none_extract,
        memory=None,
        complete_task_fn=_complete_task,
        settings=settings,
        key_provider=key_provider,
        notice_sink=list[str]().append,
        schedule_task_fn=schedule_task,
        clear_link_fn=clear_calls.append,
        mark_bill_paid_fn=_mark_bill_paid,
        reconciler=FakeReconciler(),
        fraud_notify_fn=_fraud_notify,
    )

    assert registry.get_tool("tasks.schedule") is not None
    assert registry.get_tool("reaction:email_to_task") is not None
    assert registry.get_tool("finance.mark_settlement") is not None

    task = asyncio.create_task(worker)
    try:
        bus.emit(_task_done_event())
        await dispatcher._queue.join()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert clear_calls == ["task-1"]


async def _none_linked_task_ref(_: str) -> str | None:
    return None


async def _none_extract(_: str) -> object | None:
    return None


async def _complete_task(_: str) -> object:
    return object()


async def _mark_bill_paid(_: str) -> object:
    return object()


async def _fraud_notify(_: object) -> object:
    return object()


def test_prune_older_than_uses_last_fired_at(ledger: ReactionLedger) -> None:
    ledger.record_refire("stateful", "same", now="2026-01-01T00:00:00+00:00", state_hash="a")
    ledger.record_refire("stateful", "same", now="2026-06-25T00:00:00+00:00", state_hash="b")

    db_path = ledger._db_path()
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM reaction_ledger").fetchone()
    assert count is not None
    assert int(count[0]) == 1
    assert ledger.prune_older_than("2026-03-01T00:00:00+00:00") == 0
