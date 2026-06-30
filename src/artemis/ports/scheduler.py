"""Scheduler port."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from artemis.types import EventTrigger, ScheduledJob


@runtime_checkable
class Scheduler(Protocol):
    async def schedule(self, job: ScheduledJob) -> str:
        """Register a durable time-based job (survives restart)."""
        ...

    async def on_event(
        self,
        trigger: EventTrigger,
        handler: Callable[[dict], Awaitable[None]],  # type: ignore[type-arg]
    ) -> str:
        """Register an event-based trigger."""
        ...

    async def run(self) -> None:
        """The always-on heartbeat: drain the event queue + fire due jobs."""
        ...

    def cancel(self, job_id: str) -> None: ...
