"""Async reaction dispatcher from domain events to rules and tools.

The dispatcher is intentionally thin: it builds deterministic stable keys,
uses the ledger as the durable dedup wall, routes internal reversible reactions
directly with an undoable notice, and stages external-effect reactions through
GATE. Observe mode emits WOULD notices without durable ledger writes or handler
effects. Live mode uses effect-then-claim at-least-once delivery, and queued
events at or above the cascade depth guard are dropped before rule lookup.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel

from artemis.reactions.emit import reaction_depth
from artemis.reactions.ledger import _LEDGER_TTL_DAYS, ReactionLedger
from artemis.registry import ToolRegistry
from artemis.staging.service import ActionStagingService

if TYPE_CHECKING:
    from artemis.modules.productivity.capture import CaptureService
    from artemis.reactions.emit import DomainEvent, EventBus
    from artemis.reactions.rulestore import ReactionRule, ReactionRuleStore

_A4_REACTION_REF = "reaction:email_to_task"
_PRUNE_EVERY_N_WAKES = 500


class ReactionDispatcher:
    """Drain emitted domain events and fire matching reactions."""

    def __init__(
        self,
        bus: EventBus,
        rule_store: ReactionRuleStore,
        ledger: ReactionLedger,
        tool_registry: ToolRegistry,
        staging: ActionStagingService,
        *,
        capture_service: CaptureService | None = None,
        notice_sink: Callable[[str], None] | None = None,
        mode: Literal["observe", "live"] = "observe",
        max_depth: int = 5,
        max_queue: int = 1000,
        logger: logging.Logger | None = None,
    ) -> None:
        if mode == "observe" and notice_sink is None:
            raise ValueError("notice_sink is required when mode='observe' (the WOULD audit trail)")
        self._queue: asyncio.Queue[DomainEvent] = asyncio.Queue(maxsize=max_queue)
        bus.subscribe(self._enqueue)
        self._rule_store = rule_store
        self._ledger = ledger
        self._registry = tool_registry
        self._staging = staging
        self._capture_service = capture_service
        self._notice_sink = notice_sink
        self._mode = mode
        self._max_depth = max_depth
        self._observed: set[str] = set()
        self._worker_started = False
        self._wake_count = 0
        self._log = logger or logging.getLogger("artemis.reactions.dispatcher")

    def _enqueue(self, event: DomainEvent) -> None:
        """Sync shim registered with EventBus; never blocks the emitter."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._log.warning("reaction queue full; dropping %s", event.event_type)

    def _stable_key(self, rule: ReactionRule, event: DomainEvent) -> str:
        """Compose a deterministic dedup key from rule fields, refs, and producer key."""
        parts = [rule.name]
        for field in rule.dedup_key_fields:
            value = event.dedup_key if field == "dedup_key" else event.payload.get(field)
            if value is None or value == "":
                value = _entity_ref_value(event, field)
            parts.append(str(value))
        parts.append(event.dedup_key)
        return ":".join(parts)

    async def drain_once(self) -> int:
        """Drain all currently queued events and return the number processed."""
        self._prune_ledger()
        processed = 0
        while not self._queue.empty():
            event = self._queue.get_nowait()
            processed += 1
            if event.depth >= self._max_depth:
                self._log.warning(
                    "reaction cascade depth %s reached for %s; dropping",
                    event.depth,
                    event.event_type,
                )
                self._queue.task_done()
                continue
            try:
                rules = self._rule_store.rules_for(event.event_type)
            except Exception:
                self._log.warning(
                    "reaction rule lookup failed for %s", event.event_type, exc_info=True
                )
                self._queue.task_done()
                continue
            for rule in rules:
                await self._fire(rule, event)
            self._queue.task_done()
        return processed

    async def run_forever(self) -> None:
        """Continuously consume events until cancelled."""
        if self._worker_started:
            raise RuntimeError(
                "ReactionDispatcher worker already started (single-consumer invariant)"
            )
        self._worker_started = True
        try:
            while True:
                event = await self._queue.get()
                self._wake_count += 1
                if self._wake_count % _PRUNE_EVERY_N_WAKES == 1:
                    self._prune_ledger()
                try:
                    if event.depth >= self._max_depth:
                        self._log.warning(
                            "reaction cascade depth %s reached for %s; dropping",
                            event.depth,
                            event.event_type,
                        )
                        continue
                    try:
                        rules = self._rule_store.rules_for(event.event_type)
                    except Exception:
                        self._log.warning(
                            "reaction rule lookup failed for %s",
                            event.event_type,
                            exc_info=True,
                        )
                        continue
                    for rule in rules:
                        await self._fire(rule, event)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            self._log.info("reaction dispatcher cancelled")
            raise

    def start(self) -> asyncio.Task[None]:
        """Start the single dispatcher worker on the current event loop."""
        if self._worker_started:
            raise RuntimeError(
                "ReactionDispatcher worker already started (single-consumer invariant)"
            )
        # Set the guard only AFTER create_task succeeds: if it raises (e.g. no running
        # loop) the dispatcher must remain re-startable (R1 cross-model review).
        task = asyncio.create_task(self._run_forever_started())
        self._worker_started = True
        return task

    async def _run_forever_started(self) -> None:
        try:
            while True:
                event = await self._queue.get()
                self._wake_count += 1
                if self._wake_count % _PRUNE_EVERY_N_WAKES == 1:
                    self._prune_ledger()
                try:
                    if event.depth >= self._max_depth:
                        self._log.warning(
                            "reaction cascade depth %s reached for %s; dropping",
                            event.depth,
                            event.event_type,
                        )
                        continue
                    try:
                        rules = self._rule_store.rules_for(event.event_type)
                    except Exception:
                        self._log.warning(
                            "reaction rule lookup failed for %s",
                            event.event_type,
                            exc_info=True,
                        )
                        continue
                    for rule in rules:
                        await self._fire(rule, event)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            self._log.info("reaction dispatcher cancelled")
            raise

    async def _fire(self, rule: ReactionRule, event: DomainEvent) -> None:
        """Fire one reaction, degrading failures without aborting the drain.

        Observe mode emits in-memory WOULD notices only. Live mode runs the
        effect first and commits the durable ledger claim only after success.
        """
        key = self._stable_key(rule, event)
        now = _now_iso()
        state_hash: str | None = None
        try:
            args = _reaction_args(event)
            if self._mode == "observe":
                if key in self._observed:
                    return
                # Emit the WOULD notice BEFORE consuming the dedup slot: a raising sink
                # must not permanently silence this key's audit for the session
                # (R1 cross-model review).
                self._notice_would(rule)
                self._observed.add(key)
                return

            if rule.stateful:
                state_hash = _state_hash(args)
                if self._ledger.state_hash(rule.name, key) == state_hash:
                    return
            elif self._ledger.has_fired(rule.name, key):
                return

            token = reaction_depth.set(event.depth)
            try:
                # A4-inert is the stronger, more specific invariant: an email_to_task
                # reaction is ALWAYS routed to the inert CaptureService suggestion and
                # can never be staged/executed, even if misconfigured external_effect=True.
                if rule.reaction_ref == _A4_REACTION_REF:
                    await self._suggest_email_task(args)
                elif rule.external_effect:
                    self._stage(rule, args)
                else:
                    spec = self._registry.get_tool(rule.reaction_ref)
                    validated = spec.args_schema.model_validate(args)
                    await spec.callable_ref(validated)
                    if self._notice_sink is not None:
                        self._notice_sink(f"Auto: {rule.name} fired (undoable)")
            finally:
                reaction_depth.reset(token)

            if rule.stateful:
                self._ledger.record_refire(rule.name, key, now=now, state_hash=state_hash)
            else:
                self._ledger.try_claim(rule.name, key, now=now)
        except Exception:
            self._log.warning(
                "reaction %s failed for %s", rule.name, event.event_type, exc_info=True
            )

    def _notice_would(self, rule: ReactionRule) -> None:
        if self._notice_sink is None:
            return
        if rule.reaction_ref == _A4_REACTION_REF:
            action = "suggest"
        elif rule.external_effect:
            action = "stage"
        else:
            action = "execute"
        self._notice_sink(f"WOULD {action}: {rule.name}")

    def _prune_ledger(self) -> None:
        cutoff = (datetime.now(UTC) - timedelta(days=_LEDGER_TTL_DAYS)).isoformat()
        try:
            self._ledger.prune_older_than(cutoff)
        except Exception:
            self._log.warning("reaction ledger prune failed", exc_info=True)

    def _stage(self, rule: ReactionRule, args: dict[str, object]) -> None:
        module = rule.reaction_ref.split(".", 1)[0].split(":", 1)[0]
        self._staging.stage(
            module=module,
            tool=rule.reaction_ref,
            args=args,
            summary=f"Reaction {rule.name} for {rule.event_type.value}",
            ttl=timedelta(hours=24),
        )

    async def _suggest_email_task(self, args: dict[str, object]) -> None:
        """A4 proof path: inert suggestion only, never a direct task write."""
        if self._capture_service is None:
            raise RuntimeError("CaptureService required for reaction:email_to_task")
        text = args.get("extract_summary")
        if not isinstance(text, str) or not text:
            raise ValueError("email-to-task reaction requires an extract summary")
        await self._capture_service.suggest_from_text("email", text, untrusted=True)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _entity_ref_value(event: DomainEvent, field: str) -> str:
    for ref in event.entity_refs:
        if field in {ref.module, f"{ref.module}_id", "entity_id", "entity_ref"}:
            return ref.entity_id
    return ""


def _reaction_args(event: DomainEvent) -> dict[str, object]:
    args: dict[str, object] = dict(event.payload)
    args["event_type"] = event.event_type.value
    args["source_module"] = event.source_module
    args["occurred_at"] = event.occurred_at
    args["dedup_key"] = event.dedup_key
    args["entity_refs"] = [
        {"module": ref.module, "entity_id": ref.entity_id} for ref in event.entity_refs
    ]
    return args


def _state_hash(args: dict[str, object]) -> str:
    encoded = json.dumps(_jsonable(args), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in cast(dict[object, object], value).items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
