"""Pending-action data model for gated external effects."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class ActionStatus(StrEnum):
    """Lifecycle state for a staged one-off action."""

    PENDING = "pending"
    EXECUTING = "executing"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class PendingAction(BaseModel):
    """Owner-private staged action awaiting an explicit approve/reject decision."""

    model_config = ConfigDict(frozen=True)

    id: str
    module: str
    tool: str
    args: dict[str, object]
    summary: str
    action_class: Literal["takes-action"]
    status: ActionStatus = ActionStatus.PENDING
    created_at: datetime
    expires_at: datetime
    result: dict[str, object] | None = None

    @model_validator(mode="after")
    def _validate_review_fields(self) -> Self:
        if not self.summary:
            raise ValueError("summary must not be empty")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self
