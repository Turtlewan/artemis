"""Composition root for the reactions runtime.

Application roots should mount the returned worker coroutine as one owned task
and cancel it during shutdown. Producer wiring is intentionally outside this
module: R2 passes ``bus.emit`` or ``depth_stamping_emit(bus)`` into Gmail,
calendar, finance, and trip producers at their construction sites.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import cast

from artemis.config import Settings
from artemis.identity.key_provider import KeyProvider
from artemis.modules.calendar.create_from_extract import EventExtract, HeldTentativeEvent
from artemis.modules.productivity.capture import CaptureService
from artemis.modules.productivity.tools import TaskScheduleArgs, TaskScheduleResult
from artemis.modules.travel.maps import MapsConnector
from artemis.reactions.dispatcher import ReactionDispatcher
from artemis.reactions.emit import EventBus, depth_stamping_emit
from artemis.reactions.ledger import ReactionLedger
from artemis.reactions.recipes.comms import (
    CaptureServiceLike as CommsCaptureService,
)
from artemis.reactions.recipes.comms import (
    TripAssemblerLike,
    register_comms_reactions,
)
from artemis.reactions.recipes.planning import (
    ClearLinkFn,
    ScheduleTaskFn,
    TripLookup,
    register_planning_reactions,
)
from artemis.reactions.recipes.planning import (
    MarkBillPaidFn as PlanningMarkBillPaidFn,
)
from artemis.reactions.recipes.self import (
    CaptureServiceLike as SelfCaptureService,
)
from artemis.reactions.recipes.self import (
    CompleteTaskFn,
    FraudNotifyFn,
    MarkBillPaidFn,
    ReconcilerLike,
    register_self_reactions,
)
from artemis.reactions.rulestore import TIER_A_BUILTINS, ReactionRuleStore
from artemis.recipes import Promoter, RecipeStore
from artemis.registry import ToolRegistry
from artemis.runtime_config import get_runtime_config
from artemis.staging.service import ActionStagingService


async def _missing_schedule_task_fn(_: TaskScheduleArgs) -> TaskScheduleResult:
    raise RuntimeError("schedule_task_fn is required for planning reactions")


def _missing_clear_link_fn(_: str) -> None:
    raise RuntimeError("clear_link_fn is required for planning reactions")


async def _missing_mark_bill_paid_fn(_: str) -> object:
    raise RuntimeError("mark_bill_paid_fn is required for finance reactions")


async def _missing_complete_task_fn(_: str) -> object:
    raise RuntimeError("complete_task_fn is required for self reactions")


async def _missing_fraud_notify_fn(_: object) -> object:
    raise RuntimeError("fraud_notify_fn is required for self reactions")


def compose_reactions(
    *,
    recipe_store: RecipeStore,
    promoter: Promoter,
    registry: ToolRegistry,
    staging: ActionStagingService,
    capture_service: object,
    calendar_from_extract_fn: Callable[[EventExtract, str], Awaitable[HeldTentativeEvent]],
    trip_assembler: object,
    get_linked_task_ref_fn: Callable[[str], Awaitable[str | None]],
    fetch_extract: Callable[[str], Awaitable[object | None]],
    memory: object | None,
    complete_task_fn: CompleteTaskFn | None,
    settings: Settings,
    key_provider: KeyProvider,
    notice_sink: Callable[[str], None] | None = None,
    schedule_task_fn: ScheduleTaskFn | None = None,
    clear_link_fn: ClearLinkFn | None = None,
    mark_bill_paid_fn: MarkBillPaidFn | None = None,
    reconciler: ReconcilerLike | None = None,
    fraud_notify_fn: FraudNotifyFn | None = None,
    maps: MapsConnector | None = None,
) -> tuple[EventBus, ReactionDispatcher, Coroutine[object, object, None]]:
    """Wire the reaction graph and return ``(bus, dispatcher, worker_coro)``."""
    del get_linked_task_ref_fn, fetch_extract

    bus = EventBus()
    stamped_emit = depth_stamping_emit(bus)
    ledger = ReactionLedger(settings, key_provider)
    rule_store = ReactionRuleStore(recipe_store, promoter, builtins=TIER_A_BUILTINS)
    cfg = get_runtime_config().reaction

    # Observe mode REQUIRES a real notice_sink: the WOULD audit trail is the operator's
    # only visibility before the go-live flip. Do NOT auto-create a throwaway sink here —
    # let the dispatcher ctor guard raise so callers must wire a real audit sink (ADR-032
    # Fork 3; R1 cross-model review).
    dispatcher = ReactionDispatcher(
        bus,
        rule_store,
        ledger,
        registry,
        staging,
        capture_service=cast(CaptureService, capture_service),
        notice_sink=notice_sink,
        mode=cfg.reactions_mode,
        max_depth=cfg.max_reaction_depth,
    )

    resolved_mark_bill_paid_fn = mark_bill_paid_fn or _missing_mark_bill_paid_fn
    register_planning_reactions(
        registry,
        schedule_task_fn=schedule_task_fn or _missing_schedule_task_fn,
        clear_link_fn=clear_link_fn or _missing_clear_link_fn,
        mark_bill_paid_fn=cast(PlanningMarkBillPaidFn, resolved_mark_bill_paid_fn),
        trip_assembler=cast(TripLookup, trip_assembler),
        maps=maps,
    )
    register_comms_reactions(
        registry,
        capture_service=cast(CommsCaptureService, capture_service),
        calendar_from_extract_fn=calendar_from_extract_fn,
        trip_assembler=cast(TripAssemblerLike, trip_assembler),
        memory=memory,
    )
    register_self_reactions(
        registry,
        capture_service=cast(SelfCaptureService, capture_service),
        mark_bill_paid_fn=resolved_mark_bill_paid_fn,
        complete_task_fn=complete_task_fn or _missing_complete_task_fn,
        reconciler=_RequiredReconciler() if reconciler is None else reconciler,
        fraud_notify_fn=fraud_notify_fn or cast(FraudNotifyFn, _missing_fraud_notify_fn),
        emit=stamped_emit,
    )
    return bus, dispatcher, dispatcher.run_forever()


class _RequiredReconciler:
    def match(self, target: object, candidates: object) -> object:
        del target, candidates
        raise RuntimeError("reconciler is required for self reactions")
