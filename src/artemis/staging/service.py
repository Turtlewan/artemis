"""Service layer for staging, approving, rejecting, and expiring actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from artemis.registry import ToolRegistry
from artemis.staging.model import ActionStatus, PendingAction
from artemis.staging.store import PendingActionStore


class ActionStagingService:
    """Coordinate gated action review with at-most-once execute-twin dispatch."""

    def __init__(
        self,
        store: PendingActionStore,
        tool_registry: ToolRegistry,
        *,
        default_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self.store = store
        self.tool_registry = tool_registry
        self.default_ttl = default_ttl

    def stage(
        self,
        module: str,
        tool: str,
        args: dict[str, object],
        summary: str,
        *,
        ttl: timedelta | None = None,
    ) -> PendingAction:
        """Stage validated owner-authored args for later review."""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        now = datetime.now(tz=UTC)
        action = PendingAction(
            id=str(uuid4()),
            module=module,
            tool=tool,
            args=args,
            summary=summary,
            action_class="takes-action",
            status=ActionStatus.PENDING,
            created_at=now,
            expires_at=now + effective_ttl,
        )
        self.store.stage(action)
        return action

    async def approve(self, action_id: str) -> PendingAction:
        """Approve and dispatch the internal ``{tool}_execute`` twin exactly once.

        Twin lookup and args re-validation happen before the conditional
        ``PENDING`` to ``EXECUTING`` flip, so preparation failures leave the row
        re-approvable. A failure after dispatch lands in terminal ``FAILED``,
        so it is not re-approvable. Expiry is checked before lookup and dispatch.
        """
        action = self.store.get(action_id)
        if action.status is not ActionStatus.PENDING:
            raise ValueError(f"Cannot approve action {action_id}: status is {action.status}")
        if datetime.now(tz=UTC) >= action.expires_at:
            self.store.set_status(action_id, ActionStatus.EXPIRED)
            raise ValueError(f"Action {action_id} has expired and cannot be approved")

        execute_tool_id = f"{action.tool}_execute"
        tool_spec = self.tool_registry.get_tool(execute_tool_id)
        validated_args = tool_spec.args_schema.model_validate(action.args)

        try:
            self.store.set_status_conditional(
                action_id,
                new_status=ActionStatus.EXECUTING,
                expected_status=ActionStatus.PENDING,
            )
        except ValueError as exc:
            raise ValueError(
                f"Cannot approve action {action_id}: concurrent status change detected"
            ) from exc

        try:
            result_obj = await tool_spec.callable_ref(validated_args)
        except Exception as exc:
            self.store.set_status(
                action_id,
                ActionStatus.FAILED,
                result={"error": str(exc)},
            )
            raise

        self.store.set_status(action_id, ActionStatus.APPROVED, result=result_obj.model_dump())
        return self.store.get(action_id)

    def reject(self, action_id: str) -> PendingAction:
        """Reject a pending action without dispatching it."""
        action = self.store.get(action_id)
        if action.status is not ActionStatus.PENDING:
            raise ValueError(f"Cannot reject action {action_id}: status is {action.status}")
        self.store.set_status(action_id, ActionStatus.REJECTED)
        return self.store.get(action_id)

    def list_pending(self) -> list[PendingAction]:
        """Expire stale rows, then return actions still needing owner attention."""
        self.expire_due(datetime.now(tz=UTC))
        return self.store.list_pending()

    def expire_due(self, now: datetime) -> list[PendingAction]:
        """Mark due pending actions expired without dispatching any callable."""
        expired: list[PendingAction] = []
        for action in self.store.list_pending():
            if now >= action.expires_at:
                self.store.set_status(action.id, ActionStatus.EXPIRED)
                expired.append(action)
        return expired
