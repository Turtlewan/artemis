"""The proactive worker: a fired job payload -> spine run -> proactive push."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from pydantic import BaseModel

from artemis.ports.model import ModelPort
from artemis.ports.transport import TransportPort
from artemis.spine.spine import Spine
from artemis.spine.types import Task
from artemis.types import OutboundMessage


class ProactiveJob(BaseModel):
    """Payload contract for a proactive job carried in ScheduledJob.payload."""

    goal: str
    context: str = ""
    title: str | None = None  # optional label, e.g. "Morning digest"


class ProactiveWorker:
    """Runs a proactive job through the spine and pushes the result to the owner."""

    def __init__(
        self,
        spine: Spine,
        transport: TransportPort,
        *,
        owner_identity: str,
        new_id: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self._spine = spine
        self._transport = transport
        self._owner_identity = owner_identity
        self._new_id = new_id

    async def run_job(self, payload: dict) -> None:  # type: ignore[type-arg]
        """The dispatch sink handed to the scheduler (matches Callable[[dict], Awaitable[None]])."""
        job = ProactiveJob.model_validate(payload)
        task = Task(id=self._new_id(), goal=job.goal, context=job.context)
        result = await self._spine.run(task)
        text = result.output
        if not text:
            return  # nothing worth pushing
        if job.title:
            text = f"{job.title}\n\n{text}"
        await self._transport.send(
            OutboundMessage(
                transport=self._transport.name,
                identity=self._owner_identity,
                text=text,
                proactive=True,
            )
        )


def build_proactive_worker(
    *,
    model: ModelPort,
    transport: TransportPort,
    owner_identity: str,
) -> ProactiveWorker:
    """Factory: a spine over the model router + a transport = a dispatchable worker."""
    return ProactiveWorker(Spine(model), transport, owner_identity=owner_identity)
