"""Heartbeat scheduler skeleton.

Silent-success ``HEARTBEAT_OK``, zero idle tokens (no LLM call, no
delivery — ntfy is a later milestone). The scheduler uses an ``asyncio``
tick loop, runnable standalone and cancellable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

logger = logging.getLogger(__name__)

HEARTBEAT_OK: Final[str] = "HEARTBEAT_OK"
"""Sentinel returned by a successful heartbeat tick — no hooks, no delivery."""


class Heartbeat:
    """Scheduler skeleton that ticks on a fixed interval.

    In M1 the tick runs zero real hooks and returns ``HEARTBEAT_OK``.
    """

    def __init__(
        self,
        interval_seconds: float = 60.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._interval = interval_seconds
        self._log = logger or logging.getLogger(__name__)

    def tick(self) -> str:
        """Execute one heartbeat tick.

        M1 runs zero hooks — returns ``HEARTBEAT_OK`` immediately.
        """
        self._log.debug("heartbeat tick: silent success")
        return HEARTBEAT_OK

    async def run_forever(self, *, max_ticks: int | None = None) -> None:
        """Run the heartbeat loop, optionally stopping after ``max_ticks``.

        The loop is cancellable via ``asyncio.CancelledError``.
        """
        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            self.tick()
            ticks += 1
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                self._log.debug("heartbeat cancelled after %d ticks", ticks)
                raise
