from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable

from artemis.sidecar.audio.protocol import CHANNELS, SAMPLE_RATE


class AudioCapture:
    """GATED WASAPI capture; sounddevice is imported only for hardware audio runs."""

    def __init__(self, queue: asyncio.Queue[bytes] | None = None) -> None:
        self.queue = queue if queue is not None else asyncio.Queue()
        self._stream: object | None = None
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            return
        import sounddevice as sd  # type: ignore[import-not-found]

        self._sd = sd
        self._settings = sd.WasapiSettings(exclusive=False)

    async def start(self) -> None:
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            return
        raise NotImplementedError("real sounddevice InputStream capture is GATED hardware work")

    async def stop(self) -> None:
        self._stream = None

    def format(self) -> tuple[int, int]:
        return SAMPLE_RATE, CHANNELS


class FakeCapture:
    def __init__(self, frames: Iterable[bytes] = ()) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        for frame in frames:
            self.queue.put_nowait(frame)

    async def inject(self, frame: bytes) -> None:
        await self.queue.put(frame)

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return
