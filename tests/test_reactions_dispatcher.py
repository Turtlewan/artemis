from __future__ import annotations

import logging
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic import BaseModel

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import ActionRisk, ToolSpec
from artemis.memory import EntityRef
from artemis.modules.productivity.capture import CaptureService
from artemis.reactions import DomainEvent, EventBus, EventType, ReactionDispatcher, ReactionLedger
from artemis.reactions.rulestore import ReactionRule, ReactionRuleStore, ReactionTier
from artemis.registry import ToolRegistry
from artemis.staging.model import PendingAction
from artemis.staging.service import ActionStagingService


class ReactionArgs(BaseModel):
    event_type: str
    source_module: str
    occurred_at: str
    dedup_key: str
    entity_refs: list[dict[str, str]]
    txn_id: str | None = None
    amount: float | None = None
    task_id: str | None = None
    extract_summary: str | None = None
    commitment_signal: bool | None = None


class ReactionResult(BaseModel):
    ok: bool = True


class FakeRuleStore:
    def __init__(self, rules: list[ReactionRule]) -> None:
        self._rules = rules

    def rules_for(self, event_type: EventType) -> list[ReactionRule]:
        return [rule for rule in self._rules if rule.event_type == event_type]


class FakeToolRegistry:
    def __init__(self) -> None:
        self.calls: dict[str, list[ReactionArgs]] = {}
        self.failures: set[str] = set()

    def get_tool(self, fq_name: str) -> ToolSpec:
        async def call(args: ReactionArgs) -> ReactionResult:
            self.calls.setdefault(fq_name, []).append(args)
            if fq_name in self.failures:
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
        self.calls: list[tuple[Literal["chat", "email", "calendar"], str, bool]] = []
        self.direct_task_creates = 0

    async def suggest_from_text(
        self,
        source: Literal["chat", "email", "calendar"],
        text: str,
        *,
        untrusted: bool = False,
    ) -> str:
        self.calls.append((source, text, untrusted))
        return "suggestion-1"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def ledger(tmp_path: Path) -> ReactionLedger:
    settings = Settings(data_root=tmp_path)
    key_provider = FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True)
    return ReactionLedger(settings, key_provider)


def _dispatcher(
    *,
    bus: EventBus,
    rules: list[ReactionRule],
    ledger: ReactionLedger,
    registry: FakeToolRegistry | None = None,
    staging: FakeActionStagingService | None = None,
    capture: FakeCaptureService | None = None,
    notices: list[str] | None = None,
) -> tuple[ReactionDispatcher, FakeToolRegistry, FakeActionStagingService, FakeCaptureService]:
    tool_registry = registry or FakeToolRegistry()
    action_staging = staging or FakeActionStagingService()
    capture_service = capture or FakeCaptureService()
    dispatcher = ReactionDispatcher(
        bus,
        cast(ReactionRuleStore, FakeRuleStore(rules)),
        ledger,
        cast(ToolRegistry, tool_registry),
        cast(ActionStagingService, action_staging),
        capture_service=cast(CaptureService, capture_service),
        notice_sink=notices.append if notices is not None else None,
        logger=logging.getLogger("tests.reactions.dispatcher"),
    )
    return (
        dispatcher,
        tool_registry,
        action_staging,
        capture_service,
    )


def _event(
    *,
    dedup_key: str = "event-1",
    payload: dict[str, str | int | float | bool] | None = None,
    event_type: EventType = EventType.TXN_RECORDED,
) -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        source_module="finance",
        entity_refs=(EntityRef(module="finance", entity_id="txn-1"),),
        payload=payload or {"txn_id": "txn-1", "amount": 12.5},
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key=dedup_key,
    )


def _rule(
    name: str = "rule",
    *,
    event_type: EventType = EventType.TXN_RECORDED,
    external_effect: bool = False,
    reaction_ref: str = "finance.mark_settlement",
    dedup_key_fields: tuple[str, ...] = ("txn_id",),
    stateful: bool = False,
    tier: ReactionTier = ReactionTier.A,
) -> ReactionRule:
    return ReactionRule(
        name=name,
        event_type=event_type,
        tier=tier,
        external_effect=external_effect,
        reaction_ref=reaction_ref,
        dedup_key_fields=dedup_key_fields,
        stateful=stateful,
    )


def _ledger_rows(ledger: ReactionLedger) -> list[tuple[str, str, int, str | None]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT rule_name, stable_key, fire_count, state_hash "
            "FROM reaction_ledger ORDER BY rule_name, stable_key"
        ).fetchall()
    return [(str(row[0]), str(row[1]), int(row[2]), _optional_str(row[3])) for row in rows]


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


@pytest.mark.anyio
async def test_fire_once_dedup(ledger: ReactionLedger) -> None:
    bus = EventBus()
    notices: list[str] = []
    dispatcher, registry, _staging, _capture = _dispatcher(
        bus=bus,
        rules=[_rule("settle")],
        ledger=ledger,
        notices=notices,
    )

    bus.emit(_event())
    bus.emit(_event())
    processed = await dispatcher.drain_once()

    assert processed == 2
    assert len(registry.calls["finance.mark_settlement"]) == 1
    assert ledger.try_claim("settle", "settle:txn-1:event-1", now="later") is False
    assert notices == ["Auto: settle fired (undoable)"]


@pytest.mark.anyio
async def test_stateful_refire_updates_one_row_and_skips_unchanged_state(
    ledger: ReactionLedger,
) -> None:
    bus = EventBus()
    dispatcher, registry, _staging, _capture = _dispatcher(
        bus=bus,
        rules=[_rule("stateful", stateful=True)],
        ledger=ledger,
    )

    bus.emit(_event(payload={"txn_id": "txn-1", "amount": 12.5}))
    bus.emit(_event(payload={"txn_id": "txn-1", "amount": 15.0}))
    bus.emit(_event(payload={"txn_id": "txn-1", "amount": 15.0}))
    assert await dispatcher.drain_once() == 3

    assert len(registry.calls["finance.mark_settlement"]) == 2
    rows = _ledger_rows(ledger)
    assert len(rows) == 1
    assert rows[0][0] == "stateful"
    assert rows[0][2] == 2
    assert rows[0][3] is not None


@pytest.mark.anyio
async def test_auto_routing_awaits_tool_and_emits_undoable_notice(
    ledger: ReactionLedger,
) -> None:
    bus = EventBus()
    notices: list[str] = []
    dispatcher, registry, staging, _capture = _dispatcher(
        bus=bus,
        rules=[_rule("auto")],
        ledger=ledger,
        notices=notices,
    )

    bus.emit(_event())
    assert await dispatcher.drain_once() == 1

    assert len(registry.calls["finance.mark_settlement"]) == 1
    assert staging.calls == []
    assert notices == ["Auto: auto fired (undoable)"]


@pytest.mark.anyio
async def test_external_effect_stages_without_direct_tool_dispatch(
    ledger: ReactionLedger,
) -> None:
    bus = EventBus()
    dispatcher, registry, staging, _capture = _dispatcher(
        bus=bus,
        rules=[
            _rule(
                "external",
                external_effect=True,
                reaction_ref="email.send_summary",
                tier=ReactionTier.B,
            )
        ],
        ledger=ledger,
    )

    bus.emit(_event())
    assert await dispatcher.drain_once() == 1

    assert registry.calls == {}
    assert len(staging.calls) == 1
    assert staging.calls[0]["module"] == "email"
    assert staging.calls[0]["tool"] == "email.send_summary"
    assert staging.calls[0]["summary"] == "Reaction external for txn-recorded"


@pytest.mark.anyio
async def test_a4_email_to_task_uses_inert_capture_suggestion(
    ledger: ReactionLedger,
) -> None:
    bus = EventBus()
    dispatcher, registry, staging, capture = _dispatcher(
        bus=bus,
        rules=[
            _rule(
                "reaction:email_to_task",
                event_type=EventType.EMAIL_INGESTED,
                reaction_ref="reaction:email_to_task",
                dedup_key_fields=("email_id",),
                tier=ReactionTier.B,
            )
        ],
        ledger=ledger,
    )

    bus.emit(
        _event(
            event_type=EventType.EMAIL_INGESTED,
            dedup_key="email-1",
            payload={
                "email_id": "email-1",
                "commitment_signal": True,
                "extract_summary": "Please send the report tomorrow.",
            },
        )
    )
    assert await dispatcher.drain_once() == 1

    assert capture.calls == [("email", "Please send the report tomorrow.", True)]
    assert capture.direct_task_creates == 0
    assert staging.calls == []
    assert registry.calls == {}


@pytest.mark.anyio
async def test_degrade_does_not_abort_other_reactions_and_claim_persists(
    ledger: ReactionLedger,
) -> None:
    bus = EventBus()
    registry = FakeToolRegistry()
    registry.failures.add("finance.bad")
    dispatcher, _registry, _staging, _capture = _dispatcher(
        bus=bus,
        rules=[
            _rule("bad", reaction_ref="finance.bad"),
            _rule("good", reaction_ref="finance.good"),
        ],
        ledger=ledger,
        registry=registry,
    )

    bus.emit(_event())
    assert await dispatcher.drain_once() == 1
    bus.emit(_event())
    assert await dispatcher.drain_once() == 1

    assert len(registry.calls["finance.bad"]) == 1
    assert len(registry.calls["finance.good"]) == 1
    assert ledger.try_claim("bad", "bad:txn-1:event-1", now="later") is False


@pytest.mark.anyio
async def test_privacy_args_are_scalar_payload_and_entity_refs_only(
    ledger: ReactionLedger,
) -> None:
    bus = EventBus()
    dispatcher, registry, _staging, _capture = _dispatcher(
        bus=bus,
        rules=[_rule("privacy", dedup_key_fields=("dedup_key",))],
        ledger=ledger,
    )

    bus.emit(_event(payload={"txn_id": "txn-1", "amount": 20.0}))
    assert await dispatcher.drain_once() == 1

    args = registry.calls["finance.mark_settlement"][0]
    dumped = args.model_dump()
    assert "title" not in dumped
    assert "body" not in dumped
    assert dumped["txn_id"] == "txn-1"
    assert dumped["entity_refs"] == [{"module": "finance", "entity_id": "txn-1"}]


@pytest.mark.anyio
async def test_scope_locked_ledger_degrades_without_double_fire(tmp_path: Path) -> None:
    settings = Settings(data_root=tmp_path)
    locked_ledger = ReactionLedger(settings, FakeKeyProvider({}, owner_unlocked=False))
    bus = EventBus()
    dispatcher, registry, _staging, _capture = _dispatcher(
        bus=bus,
        rules=[_rule("locked")],
        ledger=locked_ledger,
    )

    bus.emit(_event())
    assert await dispatcher.drain_once() == 1

    assert registry.calls == {}
    assert not (tmp_path / "dev" / OWNER_PRIVATE / "reactions" / "reaction_ledger.db").exists()


def test_ledger_try_claim_record_refire_and_locked_provider(tmp_path: Path) -> None:
    ledger = ReactionLedger(
        Settings(data_root=tmp_path),
        FakeKeyProvider({OWNER_PRIVATE: b"1" * 32}, owner_unlocked=True),
    )

    assert ledger.try_claim("r", "k", now="t1") is True
    assert ledger.try_claim("r", "k", now="t2") is False
    ledger.record_refire("stateful", "k", now="t1", state_hash="h1")
    ledger.record_refire("stateful", "k", now="t2", state_hash="h2")

    rows = _ledger_rows(ledger)
    assert ("r", "k", 1, None) in rows
    assert ("stateful", "k", 2, "h2") in rows

    locked = ReactionLedger(Settings(data_root=tmp_path), FakeKeyProvider({}, owner_unlocked=False))
    with pytest.raises(Exception, match="Scope is locked"):
        locked.try_claim("r", "k", now="t")


def test_ledger_database_has_single_stateful_row(ledger: ReactionLedger) -> None:
    ledger.record_refire("r", "k", now="t1", state_hash="h1")
    ledger.record_refire("r", "k", now="t2", state_hash="h2")

    db_path = ledger._db_path()
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM reaction_ledger").fetchone()
    assert count is not None
    assert int(count[0]) == 1
