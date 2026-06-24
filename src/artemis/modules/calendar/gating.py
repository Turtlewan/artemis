"""Strict runtime gate for calendar write tools.

Ordered classifier rules:
1. ``respond_to_invite`` is always gated because it acts toward others.
2. ``block_focus_time``, ``set_reminders``, and ``quick_add`` are always auto.
3. Any attendee other than the owner gates the write.
4. Otherwise the write is auto.

The gated branch never calls the write API; it only stages the action for owner
approval. Empty owner identity fails closed to ``GATED``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artemis.modules.calendar.write_tools import StagedResult, WriteResult


class GateDecision(StrEnum):
    """Calendar write gate decision."""

    AUTO = "auto"
    GATED = "gated"


def classify(tool_name: str, attendees: list[str], owner_email: str) -> GateDecision:
    """Return the strict calendar write gate decision for one tool invocation."""
    if tool_name in {"respond_to_invite"}:
        return GateDecision.GATED
    if tool_name in {"block_focus_time", "set_reminders", "quick_add"}:
        return GateDecision.AUTO
    owner = owner_email.lower().strip()
    if not owner:
        return GateDecision.GATED
    non_owner = [email for email in attendees if email.lower().strip() != owner]
    if non_owner:
        return GateDecision.GATED
    return GateDecision.AUTO


async def dispatch(
    tool_name: str,
    event_id: str | None,
    attendees: list[str],
    owner_email: str,
    *,
    execute_fn: Callable[[], Awaitable[WriteResult]],
    stage_fn: Callable[[], Awaitable[StagedResult]],
    log_fn: Callable[[WriteResult], None],
) -> WriteResult | StagedResult:
    """Classify then either execute+log or stage without executing."""
    del event_id
    decision = classify(tool_name, attendees, owner_email)
    if decision is GateDecision.AUTO:
        result = await execute_fn()
        log_fn(result)
        return result
    return await stage_fn()
