from __future__ import annotations

import os
from collections import deque


class AudioPlayback:
    """GATED sounddevice OutputStream playback with an interruptible callback queue."""

    def __init__(self) -> None:
        self._chunks: deque[bytes] = deque()
        self._stream: object | None = None
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            return
        import sounddevice as sd  # type: ignore[import-not-found]

        self._sd = sd

    def enqueue_pcm(self, data: bytes) -> None:
        self._chunks.append(data)

    def flush(self) -> None:
        self._chunks.clear()

    def pending_chunks(self) -> int:
        return len(self._chunks)


class FakePlayback:
    def __init__(self) -> None:
        self.enqueued: list[bytes] = []
        self.flush_count = 0

    @property
    def flush_called(self) -> bool:
        return self.flush_count > 0

    def enqueue_pcm(self, data: bytes) -> None:
        self.enqueued.append(data)

    def flush(self) -> None:
        self.flush_count += 1
        self.enqueued.clear()
