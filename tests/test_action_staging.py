from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError
from artemis.identity.scope import OWNER_PRIVATE
from artemis.registry import ToolRegistry
from artemis.staging import ActionStagingService, ActionStatus, PendingAction, PendingActionStore


class ActionArgs(BaseModel):
    title: str


class StrictArgs(BaseModel):
    count: int


class ActionResult(BaseModel):
    ok: bool
    title: str


class ValidatedArgs(BaseModel):
    title: str
    count: int


class SpyCallable:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.call_count = 0
        self.fail_once = fail_once

    async def __call__(self, args: BaseModel) -> BaseModel:
        self.call_count += 1
        if self.fail_once and self.call_count == 1:
            raise ScopeLockedError("owner scope relocked")
        action_args = cast(ActionArgs, args)
        return ActionResult(ok=True, title=action_args.title)


class FakeToolSpec:
    def __init__(self, args_schema: type[BaseModel], spy: SpyCallable) -> None:
        self.args_schema = args_schema
        self.callable_ref = spy


class FakeToolRegistry:
    def __init__(self, spec: FakeToolSpec) -> None:
        self.spec = spec
        self.seen_names: list[str] = []

    def get_tool(self, fq_name: str) -> FakeToolSpec:
        self.seen_names.append(fq_name)
        if fq_name != "cal.create_event_execute":
            raise KeyError(fq_name)
        return self.spec


def test_pending_action_model_validation_and_frozen() -> None:
    now = datetime.now(tz=UTC)
    action = _action("a1", created_at=now, expires_at=now + timedelta(hours=1))

    assert action.action_class == "takes-action"
    with pytest.raises(ValidationError):
        _action("a2", summary="")
    with pytest.raises(ValidationError):
        _action("a3", created_at=now, expires_at=now)
    with pytest.raises(ValidationError):
        action.status = ActionStatus.APPROVED  # type: ignore[misc]


def test_store_locked_raises_scope_locked_error(tmp_path: Path) -> None:
    store = PendingActionStore(_settings(tmp_path), FakeKeyProvider(owner_unlocked=False))

    with pytest.raises(ScopeLockedError):
        store.stage(_action("locked"))
    with pytest.raises(ScopeLockedError):
        store.get("locked")


def test_store_round_trip_and_status_updates(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _action("round-trip", args={"title": "T", "count": 2})

    store.stage(action)

    assert store.get(action.id) == action
    assert store.list_pending() == [action]
    store.set_status(action.id, ActionStatus.APPROVED, result={"ok": True})
    updated = store.get(action.id)
    assert updated.status is ActionStatus.APPROVED
    assert updated.result == {"ok": True}
    with pytest.raises(ValueError):
        store.set_status_conditional(
            action.id,
            new_status=ActionStatus.EXECUTING,
            expected_status=ActionStatus.PENDING,
        )


def test_service_stage_returns_pending_action(tmp_path: Path) -> None:
    service = _service(tmp_path)

    action = service.stage("cal", "cal.create_event", {"title": "T"}, "Create event T")

    assert action.status is ActionStatus.PENDING
    assert action.tool == "cal.create_event"
    assert action.action_class == "takes-action"
    assert action.id
    assert action.expires_at == action.created_at + timedelta(hours=24)


async def test_service_approve_dispatches_execute_twin_once(tmp_path: Path) -> None:
    spy = SpyCallable()
    service = _service(tmp_path, spy=spy)
    action = service.stage("cal", "cal.create_event", {"title": "T"}, "Create event T")

    approved = await service.approve(action.id)

    assert service.tool_registry.seen_names == ["cal.create_event_execute"]  # type: ignore[attr-defined]
    assert spy.call_count == 1
    assert approved.status is ActionStatus.APPROVED
    assert approved.result == {"ok": True, "title": "T"}
    with pytest.raises(ValueError):
        await service.approve(action.id)
    assert spy.call_count == 1


async def test_service_approve_revalidates_args_before_dispatch(tmp_path: Path) -> None:
    spy = SpyCallable()
    service = _service(tmp_path, args_schema=StrictArgs, spy=spy)
    action = service.stage("cal", "cal.create_event", {"title": "T"}, "Create event T")

    with pytest.raises(ValidationError):
        await service.approve(action.id)
    assert spy.call_count == 0
    assert service.store.get(action.id).status is ActionStatus.PENDING


async def test_service_approve_expiry_before_dispatch(tmp_path: Path) -> None:
    spy = SpyCallable()
    service = _service(tmp_path, spy=spy)
    action = service.stage(
        "cal",
        "cal.create_event",
        {"title": "T"},
        "Create event T",
        ttl=timedelta(milliseconds=1),
    )
    expired = service.expire_due(action.expires_at + timedelta(seconds=1))

    assert expired == [action]
    with pytest.raises(ValueError):
        await service.approve(action.id)
    assert spy.call_count == 0


async def test_service_approve_scope_locked_dispatch_fails_terminally(tmp_path: Path) -> None:
    spy = SpyCallable(fail_once=True)
    service = _service(tmp_path, spy=spy)
    action = service.stage("cal", "cal.create_event", {"title": "T"}, "Create event T")

    with pytest.raises(ScopeLockedError):
        await service.approve(action.id)

    failed = service.store.get(action.id)
    assert failed.status is ActionStatus.FAILED
    assert failed.result is not None
    assert failed.result["error"] == "owner scope relocked"
    with pytest.raises(ValueError):
        await service.approve(action.id)
    with pytest.raises(ValueError):
        service.reject(action.id)
    assert spy.call_count == 1


def test_service_reject_blocks_approval(tmp_path: Path) -> None:
    service = _service(tmp_path)
    action = service.stage("cal", "cal.create_event", {"title": "T"}, "Create event T")

    rejected = service.reject(action.id)

    assert rejected.status is ActionStatus.REJECTED
    with pytest.raises(ValueError):
        service.reject(action.id)


async def test_service_approve_after_reject_raises(tmp_path: Path) -> None:
    spy = SpyCallable()
    service = _service(tmp_path, spy=spy)
    action = service.stage("cal", "cal.create_event", {"title": "T"}, "Create event T")
    service.reject(action.id)

    with pytest.raises(ValueError):
        await service.approve(action.id)
    assert spy.call_count == 0


async def test_service_expire_due_and_list_pending_never_dispatch(tmp_path: Path) -> None:
    spy = SpyCallable()
    service = _service(tmp_path, spy=spy)
    action_one = service.stage(
        "cal",
        "cal.create_event",
        {"title": "One"},
        "Create event One",
        ttl=timedelta(milliseconds=1),
    )
    action_two = service.stage(
        "cal",
        "cal.create_event",
        {"title": "Two"},
        "Create event Two",
        ttl=timedelta(milliseconds=1),
    )

    expired = service.expire_due(action_two.expires_at + timedelta(seconds=1))

    assert [action.id for action in expired] == [action_one.id, action_two.id]
    assert service.list_pending() == []
    with pytest.raises(ValueError):
        await service.approve(action_one.id)
    assert spy.call_count == 0


def test_list_pending_expires_due_before_returning_store_list(tmp_path: Path) -> None:
    service = _service(tmp_path)
    expired_action = service.stage(
        "cal",
        "cal.create_event",
        {"title": "Old"},
        "Create old event",
        ttl=timedelta(milliseconds=1),
    )
    pending_action = service.stage("cal", "cal.create_event", {"title": "New"}, "Create new event")
    service.expire_due(expired_action.expires_at + timedelta(seconds=1))

    assert service.list_pending() == [pending_action]


def test_args_are_owner_authored_validated_dicts(tmp_path: Path) -> None:
    service = _service(tmp_path)
    validated = ValidatedArgs(title="T", count=1)

    action = service.stage(
        "cal",
        "cal.create_event",
        validated.model_dump(),
        "Create event T",
    )

    # Calling tools pass validated Pydantic payloads, not raw external text blobs.
    assert isinstance(action.args, dict)
    assert action.args == {"title": "T", "count": 1}


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")


def _store(tmp_path: Path) -> PendingActionStore:
    key_provider = FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True)
    return PendingActionStore(_settings(tmp_path), key_provider)


def _service(
    tmp_path: Path,
    *,
    args_schema: type[BaseModel] = ActionArgs,
    spy: SpyCallable | None = None,
) -> ActionStagingService:
    effective_spy = spy or SpyCallable()
    registry = FakeToolRegistry(FakeToolSpec(args_schema, effective_spy))
    return ActionStagingService(_store(tmp_path), cast(ToolRegistry, registry))


def _action(
    action_id: str,
    *,
    args: dict[str, object] | None = None,
    summary: str = "Do it",
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> PendingAction:
    effective_created_at = created_at or datetime.now(tz=UTC)
    effective_expires_at = expires_at or effective_created_at + timedelta(hours=1)
    return PendingAction(
        id=action_id,
        module="cal",
        tool="cal.create_event",
        args=args or {"title": "T"},
        summary=summary,
        action_class="takes-action",
        created_at=effective_created_at,
        expires_at=effective_expires_at,
    )
